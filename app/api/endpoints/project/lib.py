from fastapi import Path, Depends

async def validate_project_id(
    project_id: str = Path(..., description="The ID of the project")
):
    return project_id
