# app/tasks.py (or similar location)
import uuid
from loguru import logger
from pathlib import Path
from loro import LoroDoc, ExportMode

from app.core.config import settings
from app.core.db import async_session
from app.models.user import User
from app.repositories.user import UserDAO
from app.repositories.project.file import FileDAO
from app.repositories.project.project import ProjectDAO
from app.api.endpoints.project.crdt_handler import crdt_handler
from app.api.endpoints.project.websocket_handlers import (
    project_general_manager, get_project_channel_name
)

from app.core.config import settings
from app.core.background_tasks import background_tasks
from app.core.aiocache import cache

from app.models.project.websocket import (
    Message,
    EventScope,
    ProjectAction
)

import uuid


async def perform_project_initialization(ctx, project_id_str: str, user_id_str: str):
    """
    Huey background task to initialize a project.
    Fetches data, writes local files, and populates CRDT cache.
    """
    project_id = uuid.UUID(project_id_str)
    user_id = uuid.UUID(user_id_str)
    logger.info(f"Starting background initialization for project {project_id} by user {user_id}")

    project_channel_name = get_project_channel_name(project_id_str)

    # use cache to prevent duplicated initialization

    task_cache_key = f"task:perform_project_initialization:{project_id}/status"
    task_status = await cache.get(task_cache_key);
    if task_status == "success":
        # TODO
        # currently we send to all members
        # in the future,  we will use `send_to_client` method and `aspubsub`
        # library should be modified to also store client websocket connection information
        # in redis
        
        await project_general_manager.publish(project_channel_name, Message(
            scope=EventScope.PROJECT,
            action=ProjectAction.INITIALIZE,
            payload="success",
        ).model_dump_json())

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
                # await hivey_cache.delete(task_cache_key) # Clean up lock
                return
             
            # Add permission check here if needed, e.g.,
            # if current_project.owner_id != current_user.id and ... :
            #    logger.error(...) return

            logger.info(f"Processing files for project: {current_project.name} ({project_id})")
            project_files = await ProjectDAO.get_files(current_project)

            if not project_files:
                logger.info(f"Project {project_id} has no files to initialize.")
                # await hivey_cache.delete(task_cache_key) # Clean up lock
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
                        text_content = doc.get_text(settings.LOROCRDT_TEXT_CONTAINER_ID).to_string()
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

        await project_general_manager.publish(project_channel_name, Message(
            scope=EventScope.PROJECT,
            action=ProjectAction.INITIALIZE,
            payload="success",
        ).model_dump_json())
        
    except Exception as e:
        logger.error(
            f"Unhandled error during background initialization for project "
            f"{project_id}: {e}",
            exc_info=True
        )

        await cache.set(task_cache_key, "failed");
        
        await project_general_manager.publish(project_channel_name, Message(
            scope=EventScope.PROJECT,
            action=ProjectAction.INITIALIZE,
            payload="failed",
        ).model_dump_json())
        
saq_settings = {
    "queue": background_tasks,
    "functions": [
        perform_project_initialization
    ],
    "concurrency": 10,
}
