import asyncio
from typing import Dict, Optional, Any
from app.core.config import settings
from loguru import logger
from pathlib import Path
import os
from loro import LoroDoc, ExportMode
from abc import ABC, abstractmethod
from collections import defaultdict
import redis.asyncio as aioredis
from base64 import b64decode
# from fastapi import BackgroundTasks # only works inside FastAPI's request/response lifecycle

import time
import functools

from app.repositories.project.file import FileDAO
from app.core.aiocache import cache as hivey_cache

class CrdtHandler:
    def __init__(
        self,
        should_update_local_files: bool = False,
        should_upload_to_r2: bool = False,
        r2_upload_min_interval_seconds: float = 1.0,
        lorocrdt_text_container_id: str = "codemirror",
        temp_directory_path: Path = settings.TEMP_PROJECTS_PATH,
        cache: Any = None,
        cache_namespace: str = "crdt",  # f"{cache_namespace}{file_id}"
    ):
        if cache is None:
            self.cache = hivey_cache
            
        self.cache_namespace = cache_namespace
        self.lorocrdt_text_container_id = lorocrdt_text_container_id
        self.should_upload_to_r2 = should_upload_to_r2
        self.should_update_local_files = should_update_local_files
        self.temp_directory_path = temp_directory_path
        self.r2_upload_min_interval_seconds = r2_upload_min_interval_seconds
        
        # --- State Management for R2 Uploads ---
        # file_id -> last upload time
        self._last_upload_start_time: Dict[str, float] = {}
        # file_id -> task
        self._upload_in_progress: Dict[str, asyncio.Task] = {}
        self._upload_state_lock = asyncio.Lock()
        
        logger.info(f"Local file updates {'enabled' if should_update_local_files else 'disabled'}")
        logger.info(f"R2 uploads {'enabled' if self.should_upload_to_r2 else 'disabled'}")
        if self.should_upload_to_r2:
            logger.info(f"R2 upload minimum interval: {self.r2_upload_min_interval_seconds} seconds")
        if should_update_local_files:
            logger.info(f"Temp directory for local files: {self.temp_directory_path}")

    def get_cache_key(self, file_id: str) -> str:
        # NOTE that there is another namespace configured in `settings.cache`
        return f"{self.cache_namespace}:{file_id}" 
            
    async def cleanup(self):
        logger.info("Cleaning up CrdtHandler...")
        
        # Cancel any tasks still marked as in progress
        async with self._upload_state_lock:
            tasks_to_cancel = list(self._upload_in_progress.values())
            self._upload_in_progress.clear()
            
        for task in tasks_to_cancel:
             if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                except Exception as e:
                    logger.warning(f"Error awaiting cancelled task during cleanup: {e}")
                    
        logger.info("CrdtHandler cleanup complete.")

    # async def import_initial(self, fileid: str, crdt_snapshot: bytes):
    #     pass
        

    async def _get_doc_from_cache(self, file_id: str) -> LoroDoc:
        """Internal helper to get LoroDoc from cache snapshot."""
        key = self.get_cache_key(file_id)
        snapshot_bytes: Optional[bytes] = await self.cache.get(key)
        
        doc = LoroDoc()
        
        if snapshot_bytes:
            try:
                doc.import_(snapshot_bytes)
            except BaseException as e:
                logger.error(f"Loro import error for cached snapshot {key}: {e}. Resetting doc.")
                await self.cache.delete(key) # Remove corrupted data
        
        return doc

    async def _set_doc_to_cache(self, file_id: str, doc: LoroDoc):
        """Internal helper to set LoroDoc snapshot to cache."""
        key = self.get_cache_key(file_id)
        try:
            snapshot_bytes = doc.export(ExportMode.Snapshot())
        except BaseException as le:
             logger.error(f"Loro export error for doc {file_id} before caching: {le}")
             return
         
        await self.cache.set(key, snapshot_bytes)
    
    async def get_doc(self, file_id: str) -> LoroDoc:
        doc = await self._get_doc_from_cache(file_id)
        return doc
    
    async def _update_local_file(
        self,
        project_id: str,
        file_id: str,
        doc: LoroDoc
    ):
        try:
            text_container = doc.get_text(self.lorocrdt_text_container_id)
            content = text_container.to_string()
        except BaseException as e:
            logger.error(
                f"Could not get text content ('{self.lorocrdt_text_container_id}') from "
                f"LoroDoc for {project_id}/{file_id}: {e}"
            )
            return
        
        # FIXME file name instead of `file_id`
        target_file_path = self.temp_directory_path / project_id / file_id
        target_dir = target_file_path.parent
        
        try:
            os.makedirs(target_dir, exist_ok=True)
            # NOTE consider using asyncio.to_thread for blocking I/O if performance critical
            with open(target_file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            logger.error(f"OS error writing local file {target_file_path}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error writing local file {target_file_path}: {e}")
            
    def _upload_task_done_callback(self, file_id: str, task: asyncio.Task):
        """Callback executed when an upload task finishes (success, error, or cancel)."""
        async def cleanup_task_state():
            async with self._upload_state_lock:
                current_task = self._upload_in_progress.get(file_id)
                if current_task is task:
                    del self._upload_in_progress[file_id]
                else:
                    logger.warning(
                        f"Task mismatch during done_callback for {file_id}. Task {task}"
                        f"finished but found {current_task} in progress."
                    )
            try:
                exception = task.exception()
                if exception:
                    logger.error(f"R2 upload task for {file_id} failed with exception: {exception}", exc_info=exception)
            except asyncio.CancelledError:
                logger.debug(f"R2 upload task for {file_id} was cancelled.")
                
        asyncio.create_task(cleanup_task_state())
        
    async def _perform_r2_upload(self, file_id: str, doc: LoroDoc):
        """Performs the actual R2 upload. Fetches latest state before uploading."""
        try:
            snapshot_bytes: bytes = doc.export(ExportMode.Snapshot())
            await asyncio.to_thread(FileDAO.update_r2_file, snapshot_bytes, file_id)
            logger.debug(f"Successfully uploaded snapshot to R2 for file_id: {file_id}")
        except Exception as e:
            logger.error(f"Error during R2 upload execution for file_id {file_id}: {e}")
            raise
        
    async def receive_update(
        self, project_id: str,
        file_id: str,
        raw_data: str,
    ) -> LoroDoc | None:
        """
        Receives update, applies it, schedules R2 upload if interval passed
        and no upload is currently running for this file_id.
        """
        try:
            update_bytes = b64decode(raw_data)
        except Exception as e:
            logger.error(f"Failed to decode base64 data for {project_id}/{file_id}: {e}")
            return None
        
        try:
            doc = await self._get_doc_from_cache(file_id)
            try:
                doc.import_(update_bytes)
            except BaseException as e:
                logger.error(f"Loro import error applying update to doc {file_id}: {e}. Resetting doc.")
                empty_doc = LoroDoc()
                await self._set_doc_to_cache(file_id, empty_doc)
                return None

            await self._set_doc_to_cache(file_id, doc)
             
            if self.should_update_local_files and doc:
                asyncio.create_task(
                    self._update_local_file(project_id, file_id, doc)
                )
                
            if self.should_upload_to_r2:
                async with self._upload_state_lock:
                    # FIXME, when there is already one uploading task for file_id
                    # we should also record the newest received update(loro doc)
                    # in case there is no updates for file with file_id after
                    # `r2_upload_min_interval_seconds` so that we cannot upload
                    # the latest state of file with file_id to r2
                    if file_id in self._upload_in_progress:
                        return doc
                    
                    now = time.monotonic()
                    last_start = self._last_upload_start_time.get(file_id, 0.0)
                    if (now - last_start) >= self.r2_upload_min_interval_seconds:
                        logger.debug(f"Scheduling R2 upload for {file_id}. Interval passed.")
                        self._last_upload_start_time[file_id] = now
                        upload_task = asyncio.create_task(self._perform_r2_upload(file_id, doc))
                        self._upload_in_progress[file_id] = upload_task
                        callback = functools.partial(self._upload_task_done_callback, file_id)
                        upload_task.add_done_callback(callback)
                        
            return doc
        
        except Exception as e:
            logger.error(f"Failed to process update or schedule upload for {project_id}/{file_id}: {e}")
            return None


crdt_handler = CrdtHandler(
    lorocrdt_text_container_id=settings.LOROCRDT_TEXT_CONTAINER_ID,
    should_upload_to_r2=True
)
