from fastapi import APIRouter, Path, Depends

router = APIRouter()

# Each endpoint needs to include the project_id parameter
@router.get("/")
async def list_files(
    project_id: str = Path(..., description="The ID of the project")
):
    return {"project_id": project_id, "files": []}

@router.get("/{file_id}")
async def get_file(
    file_id: str,
    project_id: str = Path(..., description="The ID of the project")
):
    return {"project_id": project_id, "file_id": file_id}
