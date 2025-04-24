# app/tasks.py (or similar location)
import uuid
from loguru import logger
from loro import ExportMode, LoroDoc
import asyncio
from typing import Optional
from pathlib import Path
from app.core.config import settings
from app.core.db import async_session, engine
from app.repositories.user import UserDAO
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from app.api.endpoints.project.crdt_handler import crdt_handler

from app.core.config import settings
from app.core.background_tasks import background_tasks
from app.core.aiocache import cache, get_cache_key_task_ppi, get_cache_key_crdt
from app.core.constants import LOROCRDT_TEXT_CONTAINER_ID
import os

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
    cache_key = get_cache_key_crdt(file_id)
    
    snapshot_bytes: Optional[bytes] = await cache.get(cache_key)
    if not snapshot_bytes:
        logger.warning(f"No CRDT data found in cache for {file_id} during R2 upload task. Skipping.")
        return {"status": "skipped", "reason": "no data in cache"}
    
    try:
        await asyncio.to_thread(FileDAO.update_r2_file, snapshot_bytes, file_id)
        logger.info(f"Successfully uploaded snapshot to R2 via SAQ task for file_id: {file_id}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error during R2 upload execution in SAQ task for {file_id}: {e}")
        raise


def write_file_sync(file_path: str | Path, content: str):
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)


async def update_local_project_file(ctx, project_id_str: str, file_id_str: str):
    cache_key = get_cache_key_crdt(file_id_str)
    snapshot_bytes: Optional[bytes] = await cache.get(cache_key)
    if not snapshot_bytes:
        logger.warning(
            f"No CRDT data found in cache for {file_id_str} during R2 upload"
            "task. Skipping."
        )
        return

    doc = LoroDoc()
    try:
        doc.import_(snapshot_bytes)
        text_content = doc.get_text(LOROCRDT_TEXT_CONTAINER_ID).to_string()
    except BaseException:
        logger.error("Get text content error")
        return

    file_id = uuid.UUID(file_id_str)
    async with async_session() as db:
        file = await FileDAO.get_file_by_id(file_id, db)
        if file is None:
            logger.error(f"file {file_id_str} doesn't exist in database")
            return
        
    filepath = file.filepath
    filename = file.filename
    target_file_path = settings.TEMP_PROJECTS_PATH / project_id_str / filepath / filename
    target_dir = target_file_path.parent
    
    try:
        os.makedirs(target_dir, exist_ok=True)
        await asyncio.to_thread(write_file_sync, target_file_path, text_content)
        logger.info(f"Successfully updated local file {target_file_path}")
    except OSError as e:
        logger.error(f"OS error writing local file {target_file_path}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error writing local file {target_file_path}: {e}")



async def shutdown(ctx):
    await engine.dispose()

        
saq_settings = {
    "queue": background_tasks,
    "functions": [
        perform_project_initialization,
        upload_crdt_snapshot_to_r2,
        update_local_project_file
    ],
    "shutdown": shutdown,
    "concurrency": 10,
}
