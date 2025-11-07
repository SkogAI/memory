"""Project management tools for Basic Memory MCP server.

These tools allow users to switch between projects, list available projects,
and manage project context during conversations.
"""

import os
from fastmcp import Context

from basic_memory.mcp.async_client import client
from basic_memory.mcp.server import mcp
from basic_memory.mcp.tools.utils import call_get, call_post, call_delete
from basic_memory.schemas.project_info import (
    ProjectList,
    ProjectStatusResponse,
    ProjectInfoRequest,
)
from basic_memory.utils import generate_permalink


@mcp.tool("list_memory_projects")
async def list_memory_projects(context: Context | None = None) -> str:
    """List all available projects with their status.

    Shows all Basic Memory projects that are available for MCP operations.
    Use this tool to discover projects when you need to know which project to use.

    Use this tool:
    - At conversation start when project is unknown
    - When user asks about available projects
    - Before any operation requiring a project

    After calling:
    - Ask user which project to use
    - Remember their choice for the session

    Returns:
        Formatted list of projects with session management guidance

    Example:
        list_memory_projects()
    """
    if context:  # pragma: no cover
        await context.info("Listing all available projects")

    # Check if server is constrained to a specific project
    constrained_project = os.environ.get("BASIC_MEMORY_MCP_PROJECT")

    # Get projects from API
    response = await call_get(client, "/projects/projects")
    project_list = ProjectList.model_validate(response.json())

    if constrained_project:
        result = f"Project: {constrained_project}\n\n"
        result += "Note: This MCP server is constrained to a single project.\n"
        result += "All operations will automatically use this project."
    else:
        # Show all projects with session guidance
        result = "Available projects:\n"

        for project in project_list.projects:
            result += f"• {project.name}\n"

    return add_project_metadata(result, current)


@mcp.tool()
async def switch_project(project_name: str, ctx: Context | None = None) -> str:
    """Switch to a different project context.

    Changes the active project context for all subsequent tool calls.
    Shows a project summary after switching successfully.

    Args:
        project_name: Name of the project to switch to

    Returns:
        Confirmation message with project summary

    Example:
        switch_project("work-notes")
        switch_project("personal-journal")
    """
    if ctx:  # pragma: no cover
        await ctx.info(f"Switching to project: {project_name}")

    current_project = session.get_current_project()
    try:
        # Validate project exists by getting project list
        response = await call_get(client, "/projects/projects")
        project_list = ProjectList.model_validate(response.json())

        # Check if project exists (case-insensitive)
        matching_project = None
        for p in project_list.projects:
            if p.name.lower() == project_name.lower():
                matching_project = p
                break
        
        if not matching_project:
            available_projects = [p.name for p in project_list.projects]
            return f"Error: Project '{project_name}' not found. Available projects: {', '.join(available_projects)}"
        
        # Use the actual project name from the list (correct case)
        actual_project_name = matching_project.name

        # Switch to the project
        session.set_current_project(actual_project_name)
        current_project = session.get_current_project()
        project_config = get_project_config(current_project)

        # Get project info to show summary
        try:
            response = await call_get(
                client,
                f"{project_config.project_url}/project/info",
                params={"project_name": actual_project_name},
            )
            project_info = ProjectInfoResponse.model_validate(response.json())

            result = f"✓ Switched to {actual_project_name} project\n\n"
            result += "Project Summary:\n"
            result += f"• {project_info.statistics.total_entities} entities\n"
            result += f"• {project_info.statistics.total_observations} observations\n"
            result += f"• {project_info.statistics.total_relations} relations\n"

        except Exception as e:
            # If we can't get project info, still confirm the switch
            logger.warning(f"Could not get project info for {actual_project_name}: {e}")
            result = f"✓ Switched to {actual_project_name} project\n\n"
            result += "Project summary unavailable.\n"

        return add_project_metadata(result, actual_project_name)

    except Exception as e:
        logger.error(f"Error switching to project {project_name}: {e}")
        # Revert to previous project on error
        session.set_current_project(current_project)

        # Return user-friendly error message instead of raising exception
        return dedent(f"""
            # Project Switch Failed

            Could not switch to project '{project_name}': {str(e)}

            ## Current project: {current_project}
            Your session remains on the previous project.

            ## Troubleshooting:
            1. **Check available projects**: Use `list_projects()` to see valid project names
            2. **Verify spelling**: Ensure the project name is spelled correctly
            3. **Check permissions**: Verify you have access to the requested project
            4. **Try again**: The error might be temporary

            ## Available options:
            - See all projects: `list_projects()`
            - Stay on current project: `get_current_project()`
            - Try different project: `switch_project("correct-project-name")`

            If the project should exist but isn't listed, send a message to support@basicmachines.co.
            """).strip()


@mcp.tool()
async def get_current_project(ctx: Context | None = None) -> str:
    """Show the currently active project and basic stats.

    Displays which project is currently active and provides basic information
    about it.

    Returns:
        Current project name and basic statistics

    Example:
        get_current_project()
    """
    if ctx:  # pragma: no cover
        await ctx.info("Getting current project information")

    current_project = session.get_current_project()
    project_config = get_project_config(current_project)
    result = f"Current project: {current_project}\n\n"

    # get project stats
    response = await call_get(
        client,
        f"{project_config.project_url}/project/info",
        params={"project_name": current_project},
    )
    project_info = ProjectInfoResponse.model_validate(response.json())

    return result


@mcp.tool("create_memory_project")
async def create_memory_project(
    project_name: str, project_path: str, set_default: bool = False, context: Context | None = None
) -> str:
    """Create a new Basic Memory project.

    Creates a new project with the specified name and path. The project directory
    will be created if it doesn't exist. Optionally sets the new project as default.

    Args:
        project_name: Name for the new project (must be unique)
        project_path: File system path where the project will be stored
        set_default: Whether to set this project as the default (optional, defaults to False)

    Returns:
        Confirmation message with project details

    Example:
        create_memory_project("my-research", "~/Documents/research")
        create_memory_project("work-notes", "/home/user/work", set_default=True)
    """
    # Check if server is constrained to a specific project
    constrained_project = os.environ.get("BASIC_MEMORY_MCP_PROJECT")
    if constrained_project:
        return f'# Error\n\nProject creation disabled - MCP server is constrained to project \'{constrained_project}\'.\nUse the CLI to create projects: `basic-memory project add "{project_name}" "{project_path}"`'

    if context:  # pragma: no cover
        await context.info(f"Creating project: {project_name} at {project_path}")

    # Create the project request
    project_request = ProjectInfoRequest(
        name=project_name, path=project_path, set_default=set_default
    )

    # Call API to create project
    response = await call_post(client, "/projects/projects", json=project_request.model_dump())
    status_response = ProjectStatusResponse.model_validate(response.json())

    result = f"✓ {status_response.message}\n\n"

    if status_response.new_project:
        result += "Project Details:\n"
        result += f"• Name: {status_response.new_project.name}\n"
        result += f"• Path: {status_response.new_project.path}\n"

        if set_default:
            result += "• Set as default project\n"

    result += "\nProject is now available for use in tool calls.\n"
    result += f"Use '{project_name}' as the project parameter in MCP tool calls.\n"

    return result


@mcp.tool()
async def delete_project(project_name: str, context: Context | None = None) -> str:
    """Delete a Basic Memory project.

    Removes a project from the configuration and database. This does NOT delete
    the actual files on disk - only removes the project from Basic Memory's
    configuration and database records.

    Args:
        project_name: Name of the project to delete

    Returns:
        Confirmation message about project deletion

    Example:
        delete_project("old-project")

    Warning:
        This action cannot be undone. The project will need to be re-added
        to access its content through Basic Memory again.
    """
    # Check if server is constrained to a specific project
    constrained_project = os.environ.get("BASIC_MEMORY_MCP_PROJECT")
    if constrained_project:
        return f"# Error\n\nProject deletion disabled - MCP server is constrained to project '{constrained_project}'.\nUse the CLI to delete projects: `basic-memory project remove \"{project_name}\"`"

    if context:  # pragma: no cover
        await context.info(f"Deleting project: {project_name}")

    # Get project info before deletion to validate it exists
    response = await call_get(client, "/projects/projects")
    project_list = ProjectList.model_validate(response.json())

    # Find the project by name (case-insensitive) or permalink - same logic as switch_project
    project_permalink = generate_permalink(project_name)
    target_project = None
    for p in project_list.projects:
        # Match by permalink (handles case-insensitive input)
        if p.permalink == project_permalink:
            target_project = p
            break
        # Also match by name comparison (case-insensitive)
        if p.name.lower() == project_name.lower():
            target_project = p
            break

    if not target_project:
        available_projects = [p.name for p in project_list.projects]
        raise ValueError(
            f"Project '{project_name}' not found. Available projects: {', '.join(available_projects)}"
        )
    
    # Use the actual project name from the list (correct case)
    actual_project_name = matching_project.name

    # Call API to delete project using URL encoding for special characters
    from urllib.parse import quote

    encoded_name = quote(target_project.name, safe="")
    response = await call_delete(client, f"/projects/{encoded_name}")
    status_response = ProjectStatusResponse.model_validate(response.json())

    result = f"✓ {status_response.message}\n\n"

    if status_response.old_project:
        result += "Removed project details:\n"
        result += f"• Name: {status_response.old_project.name}\n"
        if hasattr(status_response.old_project, "path"):
            result += f"• Path: {status_response.old_project.path}\n"

    result += "Files remain on disk but project is no longer tracked by Basic Memory.\n"
    result += "Re-add the project to access its content again.\n"

    return result
