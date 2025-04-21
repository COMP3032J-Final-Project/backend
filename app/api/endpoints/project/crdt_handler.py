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
from fastapi import BackgroundTasks

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
            snapshot_bytes: bytes = doc.export(ExportMode.ShallowSnapshot(doc.state_frontiers))
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
        lorocrdt_text_container_id: str = "codemirror",
        temp_directory_path: Path = settings.TEMP_PROJECTS_PATH,
    ):
        if backend:
            self.backend = backend
        else:
            if backend_url is None:
                raise Exception("Parameter `backend_url` and `backend` cannot both be None!")
            if backend_url.startswith("memory://"):
                self.backend = CrdtInMemoryBackend()
            else:
                self.backend = CrdtRedisBackend(backend_url)
                
        self.lorocrdt_text_container_id = lorocrdt_text_container_id
        self.should_upload_to_r2 = should_upload_to_r2
        self.should_update_local_files = should_update_local_files
        self.temp_directory_path = temp_directory_path
        self.background_tasks = BackgroundTasks()
                
        logger.info(f"Initialized CrdtHandler with backend: {type(backend).__name__}")
        logger.info(f"Local file updates {'enabled' if should_update_local_files else 'disabled'}")
        logger.info(f"R2 uploads {'enabled' if self.should_upload_to_r2 else 'disabled'}") 
        if should_update_local_files:
            logger.info(f"Temp directory for local files: {temp_directory_path}")


    async def initialize(self):
        await self.backend.connect()

    async def cleanup(self):
        await self.backend.disconnect()

    async def get_doc(self, file_id: str):
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
        except Exception as e:
            logger.error(
                f"Could not get text content ('{self.lorocrdt_text_container_id}') from"
                f" LoroDoc for {project_id}/{file_id}: {e}"
            )
            return

        target_file_path = self.temp_directory_path / project_id / file_id
        target_dir = target_file_path.parent

        try:
            os.makedirs(target_dir, exist_ok=True)
            with open(target_file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            logger.error(f"OS error writing local file {target_file_path}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error writing local file {target_file_path}: {e}")

    async def _upload_to_r2(self, file_id, doc: LoroDoc):
        snapshot_bytes: bytes = doc.export(ExportMode.ShallowSnapshot(doc.state_frontiers))
        logger.warning("hello")
        FileDAO.update_r2_file(snapshot_bytes, file_id)

    async def receive_update(
        self, project_id: str,
        file_id: str,
        raw_data: str,
    ) -> LoroDoc | None:
        """
        Receives a base64 data, decode it into loro-crdt binary, applies it using the backend,
        and optionally updates local files. Returns the updated doc or None on error.
        """
        data = b64decode(raw_data)
        try:
            updated_doc = await self.backend.apply_update(file_id, data)
            logger.debug(updated_doc.get_text(self.lorocrdt_text_container_id).to_string())

            # Schedule background tasks IF content extraction was successful (or decide otherwise)
            if self.should_update_local_files:
                self.background_tasks.add_task(
                    self._update_local_file,
                    project_id,
                    file_id,
                    updated_doc
                )
                
            if self.should_upload_to_r2:
                self.background_tasks.add_task(
                    self._upload_to_r2,
                    file_id,
                    updated_doc
                )
                
            if self.should_update_local_files and updated_doc:
                await self._update_local_file(project_id, file_id, updated_doc)


            return updated_doc

        except Exception as e:
            logger.error(f"Failed to process update for {project_id}/{file_id}: {e}")
            return None


crdt_handler = CrdtHandler(
    backend_url=settings.CRDT_HANDLER_BACKEND_URL,
    should_upload_to_r2=True
)
