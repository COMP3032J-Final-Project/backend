# app/tasks.py (or similar location)
import uuid
from loguru import logger
from loro import LoroDoc
import asyncio
from typing import Optional

from app.core.config import settings
from app.core.db import async_session
from app.repositories.user import UserDAO
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from app.api.endpoints.project.crdt_handler import crdt_handler

from app.core.config import settings
from app.core.background_tasks import background_tasks
from app.core.aiocache import cache, get_cache_key_task_ppi, get_cache_key_crdt
from app.core.constants import LOROCRDT_TEXT_CONTAINER_ID

import uuid

async def perform_project_initialization(ctx, project_id_str: str, user_id_str: str):
    """
    Huey background task to initialize a project.
    Fetches data, writes local files, and populates CRDT cache.
    """
    project_id = uuid.UUID(project_id_str)
    user_id = uuid.UUID(user_id_str)
    logger.info(f"Starting background initialization for project {project_id} by user {user_id}")

    # use cache to prevent duplicated initialization

    task_cache_key = get_cache_key_task_ppi(project_id_str)
    task_status = await cache.get(task_cache_key)

    if task_status in (b"success", "success"):
        return

    try:
        async with async_session() as db:
            current_user = await UserDAO.get_user_by_id(user_id, db)
            if not current_user:
                logger.error(f"Background Init: User {user_id} not found.")
                # await hivey_cache.delete(task_cache_key) # Clean up lock
                return

            current_project = await ProjectDAO.get_project_by_id(project_id, db)
            if not current_project:
                logger.error(f"Background Init: Project {project_id} not found.")
                await cache.set(task_cache_key, "failed");
                return
            
            logger.info(f"Processing files for project: {current_project.name} ({project_id})")
            project_files = await ProjectDAO.get_files(current_project)

            if not project_files:
                logger.info(f"Project {project_id} has no files to initialize.")
                await cache.set(task_cache_key, "success");
                return

            # --- Process each file ---
            for file in project_files:
                logger.debug(f"Initializing file: {file.filename} ({file.id})")
                try:
                    fileobj_bytes = FileDAO.get_r2_file_data(file.id)

                    doc = LoroDoc()
                    is_binary = False
                    try:
                        doc.import_(fileobj_bytes)
                    except:
                        is_binary = True

                    target_path = settings.TEMP_PROJECTS_PATH / str(project_id) / file.filename
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    if is_binary:
                        # Use async file I/O if possible, or run sync I/O in a thread
                        # For simplicity, using sync here, but consider aiofiles or asyncio.to_thread
                        target_path.write_bytes(fileobj_bytes)
                    else:
                        text_content = doc.get_text(LOROCRDT_TEXT_CONTAINER_ID).to_string()
                        # Use async file I/O if possible
                        target_path.write_text(text_content, encoding='utf-8')

                        # Set initial snapshot for crdt_handler cache
                        await crdt_handler._set_doc_to_cache(str(file.id), doc)
                        logger.debug(f"Set initial CRDT snapshot cache for file {file.id}")

                except Exception as e:
                    logger.error(
                        f"Error processing file {file.filename} ({file.id}) for project "
                        f"{project_id}: {e}",
                        exc_info=True
                    )

        logger.info(f"Successfully finished background initialization for project {project_id}")
        
        await cache.set(task_cache_key, "success");
        
    except Exception as e:
        logger.error(
            f"Unhandled error during background initialization for project "
            f"{project_id}: {e}",
            exc_info=True
        )

        await cache.set(task_cache_key, "failed");




# --- crdt ----


async def upload_crdt_snapshot_to_r2(ctx, file_id: str):
    """
    SAQ task to upload the latest CRDT snapshot from cache to R2.
    """
    doc = LoroDoc()
    snapshot_bytes: bytes | None = None
    cache_key = get_cache_key_crdt(file_id)
    
    cached_data: Optional[bytes] = await cache.get(cache_key)
    if not cached_data:
        logger.warning(f"No CRDT data found in cache for {file_id} during R2 upload task. Skipping.")
        return {"status": "skipped", "reason": "no data in cache"}
    
    snapshot_bytes = cached_data
    
    try:
        await asyncio.to_thread(FileDAO.update_r2_file, snapshot_bytes, file_id)
        logger.info(f"Successfully uploaded snapshot to R2 via SAQ task for file_id: {file_id}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error during R2 upload execution in SAQ task for {file_id}: {e}")
        raise








        
saq_settings = {
    "queue": background_tasks,
    "functions": [
        perform_project_initialization,
        upload_crdt_snapshot_to_r2
    ],
    "concurrency": 10,
}
