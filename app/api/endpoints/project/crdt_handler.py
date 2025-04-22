import asyncio
from typing import Dict, Optional
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


class CrdtBackend(ABC):
    """Abstract base class for CRDT document storage."""
    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass


    @abstractmethod
    async def set(self, file_id: str, doc: LoroDoc) -> None:
        """Stores the entire state of the LoroDoc."""
        pass

    @abstractmethod
    async def get(self, file_id: str) -> LoroDoc:
        """Retrieves the LoroDoc, potentially creating a new one if not found."""
        pass

    @abstractmethod
    async def apply_update(self, file_id: str, update: bytes) -> LoroDoc:
        """
        Applies a delta update to the document specified by file_id.
        Returns the updated LoroDoc object.
        This is often the primary interaction method besides initial get.
        """
        pass

class CrdtInMemoryBackend(CrdtBackend):
    """Stores LoroDocs directly in an in-memory dictionary."""
    def __init__(self):
        pass

    async def connect(self):
        self._dict: Dict[str, LoroDoc] = defaultdict(LoroDoc)
        logger.info("Initialized CrdtInMemoryBackend")

    async def disconnect(self):
        self._dict.clear()

    async def set(self, file_id: str, doc: LoroDoc):
        self._dict[file_id] = doc

    async def get(self, file_id: str) -> LoroDoc:
        doc = self._dict[file_id]
        return doc

    async def apply_update(self, file_id: str, update: bytes) -> LoroDoc:
        doc = self._dict[file_id]
        try:
            doc.import_(update)
        except BaseException as e:
            logger.error(f"Error applying update to in-memory doc {file_id}: {e}")
            await self.set(file_id, LoroDoc())
            raise Exception(e)

        return doc

# --- Redis Backend Implementation ---
class CrdtRedisBackend(CrdtBackend):
    """Stores LoroDoc snapshots in Redis."""
    def __init__(self, url: str):
        self._url = url

    async def connect(self):
        self.conn = aioredis.Redis.from_url(self._url, health_check_interval=30)
        logger.info(f"Initialized CrdtRedisBackend connected to {self._url}")

    async def disconnect(self):
        if self.conn:
            await self.conn.aclose()

    def _get_redis_key(self, file_id: str) -> str:
        """Generates the Redis key for a given file_id."""
        return f"hivey:crdt:{file_id}"

    async def set(self, file_id: str, doc: LoroDoc) -> None:
        """Exports snapshot and stores it in Redis."""
        key = self._get_redis_key(file_id)
        try:
            snapshot_bytes: bytes = doc.export(ExportMode.Snapshot())
            await self.conn.set(key, snapshot_bytes)
        except Exception as e:
            logger.error(f"Error setting Redis key {key}: {e}")
            raise

    async def get(self, file_id: str) -> LoroDoc:
        """Retrieves snapshot from Redis and imports into a new LoroDoc."""
        key = self._get_redis_key(file_id)
        doc = LoroDoc()
        try:
            snapshot_bytes: Optional[bytes] = await self.conn.get(key)
            if snapshot_bytes:
                doc.import_(snapshot_bytes)
        except BaseException as e:
            logger.error(f"Error getting or importing Redis key {key}: {e}")
            # TODO better handling
            # Don't raise error since some key may already exists and is not
            # loro-crdt format
        return doc

    async def apply_update(self, file_id: str, update: bytes) -> LoroDoc:
        # TODO use Redis transactions
        doc = await self.get(file_id)
        try:
            doc.import_(update)
        except BaseException as e:
            logger.error(f"Error applying update to doc {file_id}: {e}")
            await self.set(file_id, LoroDoc())
            raise Exception(e)
        await self.set(file_id, doc)
        return doc


# --- CRDT Handler Class ---
class CrdtHandler:
    def __init__(
        self,
        backend_url: Optional[str] = None,
        backend: Optional[CrdtBackend] = None,
        should_update_local_files: bool = False,
        should_upload_to_r2: bool = False,
        r2_upload_min_interval_seconds: float = 1.0,
        lorocrdt_text_container_id: str = "codemirror",
        temp_directory_path: Path = settings.TEMP_PROJECTS_PATH,
    ):
        # Backend initialization (same as before)
        if backend:
            self.backend = backend
        elif backend_url:
            if backend_url.startswith("memory://"):
                self.backend = CrdtInMemoryBackend()
            else:
                self.backend = CrdtRedisBackend(backend_url)
        else:
            logger.warning("No backend_url or backend provided, defaulting to CrdtInMemoryBackend.")
            self.backend = CrdtInMemoryBackend()
            
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
        
        logger.info(f"Initialized CrdtHandler with backend: {type(self.backend).__name__}")
        logger.info(f"Local file updates {'enabled' if should_update_local_files else 'disabled'}")
        logger.info(f"R2 uploads {'enabled' if self.should_upload_to_r2 else 'disabled'}")
        if self.should_upload_to_r2:
            logger.info(f"R2 upload minimum interval: {self.r2_upload_min_interval_seconds} seconds")
        if should_update_local_files:
            logger.info(f"Temp directory for local files: {self.temp_directory_path}")

            
    async def initialize(self):
        await self.backend.connect()
        
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
                    
        await self.backend.disconnect()
        logger.info("CrdtHandler cleanup complete.")
        
    async def get_doc(self, file_id: str) -> LoroDoc:
        doc = await self.backend.get(file_id)
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
        
    async def _perform_r2_upload(self, file_id: str):
        """Performs the actual R2 upload. Fetches latest state before uploading."""
        try:
            doc = await self.backend.get(file_id)
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
            data = b64decode(raw_data)
        except Exception as e:
            logger.error(f"Failed to decode base64 data for {project_id}/{file_id}: {e}")
            return None
        
        updated_doc: Optional[LoroDoc] = None
        
        try:
            updated_doc = await self.backend.apply_update(file_id, data)
            if self.should_update_local_files and updated_doc:
                asyncio.create_task(
                    self._update_local_file(project_id, file_id, updated_doc)
                )
                
            if self.should_upload_to_r2:
                async with self._upload_state_lock:
                    # FIXME, when there is already one uploading task for file_id
                    # we should also record the newest received update(loro doc)
                    # in case there is no updates for file with file_id after
                    # `r2_upload_min_interval_seconds` so that we cannot upload
                    # the latest state of file with file_id to r2
                    if file_id in self._upload_in_progress:
                        return updated_doc
                    
                    now = time.monotonic()
                    last_start = self._last_upload_start_time.get(file_id, 0.0)
                    if (now - last_start) >= self.r2_upload_min_interval_seconds:
                        logger.debug(f"Scheduling R2 upload for {file_id}. Interval passed.")
                        self._last_upload_start_time[file_id] = now
                        upload_task = asyncio.create_task(self._perform_r2_upload(file_id))
                        self._upload_in_progress[file_id] = upload_task
                        callback = functools.partial(self._upload_task_done_callback, file_id)
                        upload_task.add_done_callback(callback)
                        
            return updated_doc
        
        except ConnectionError as e:
            logger.error(f"Backend connection error processing update for {project_id}/{file_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to process update or schedule upload for {project_id}/{file_id}: {e}")
            return updated_doc if updated_doc else None


crdt_handler = CrdtHandler(
    backend_url=settings.CRDT_HANDLER_BACKEND_URL,
    should_upload_to_r2=True
)
