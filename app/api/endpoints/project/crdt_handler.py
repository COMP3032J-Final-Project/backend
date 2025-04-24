import asyncio
from typing import Dict, Optional, Any
from app.core.config import settings
from loguru import logger
from pathlib import Path
import os
from loro import LoroDoc, ExportMode
from base64 import b64decode
# from fastapi import BackgroundTasks # only works inside FastAPI's request/response lifecycle

from app.core.aiocache import (
    cache, get_cache_key_crdt, get_cache_key_crdt_upload_r2_debounce,
    get_cache_key_crdt_write_local_file_debounce
)
from app.core.background_tasks import background_tasks
from app.core.constants import LOROCRDT_TEXT_CONTAINER_ID


class CrdtHandler:
    def __init__(
        self,
        should_update_local_files: bool = False,
        should_upload_to_r2: bool = False,
        lorocrdt_text_container_id: str = "codemirror",
        debounce_ttl: float = 1.0,
    ):
            
        self.lorocrdt_text_container_id = lorocrdt_text_container_id
        self.should_upload_to_r2 = should_upload_to_r2
        self.should_update_local_files = should_update_local_files
        self.debounce_ttl = debounce_ttl
        
        # --- State Management for R2 Uploads ---
        # file_id -> last upload time
        self._last_upload_start_time: Dict[str, float] = {}
        # file_id -> task
        self._upload_in_progress: Dict[str, asyncio.Task] = {}
        self._upload_state_lock = asyncio.Lock()
        
        logger.info(f"Local file updates {'enabled' if should_update_local_files else 'disabled'}")
        logger.info(f"R2 uploads {'enabled' if self.should_upload_to_r2 else 'disabled'}")

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
        key = get_cache_key_crdt(file_id)
        snapshot_bytes: Optional[bytes] = await cache.get(key)
        
        doc = LoroDoc()
        
        if snapshot_bytes:
            try:
                doc.import_(snapshot_bytes)
            except BaseException as e:
                logger.error(f"Loro import error for cached snapshot {key}: {e}. Resetting doc.")
                await cache.delete(key) # Remove corrupted data
        
        return doc

    async def _set_doc_to_cache(self, file_id: str, doc: LoroDoc):
        """Internal helper to set LoroDoc snapshot to cache."""
        key = get_cache_key_crdt(file_id)
        try:
            snapshot_bytes = doc.export(ExportMode.Snapshot())
        except BaseException as le:
             logger.error(f"Loro export error for doc {file_id} before caching: {le}")
             return
         
        await cache.set(key, snapshot_bytes)
    
    async def get_doc(self, file_id: str) -> LoroDoc:
        doc = await self._get_doc_from_cache(file_id)
        return doc

    async def receive_update(
        self, project_id: str,
        file_id: str,
        raw_data: str,
    ) -> LoroDoc | None:
        """
        For tasks 
        FIXME
        Imaging that we already received an update, and we of course  enqueue  the
        task immediately. It's possible there is an updates comes directly after the
        previous update, and we don't do anything. What if there is no more updates?
        so that we don't upload the latest file to r2.

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
                debounce_key = get_cache_key_crdt_write_local_file_debounce(file_id)
                debounce_status = await cache.get(debounce_key)
                if debounce_status is None:
                    await background_tasks.enqueue(
                        "update_local_project_file",
                        project_id_str=project_id,
                        file_id_str=file_id
                    )
                    await cache.set(
                        debounce_key,
                        "debounce",
                        ttl=self.debounce_ttl
                    )
                
            if self.should_upload_to_r2:
                debounce_key = get_cache_key_crdt_upload_r2_debounce(file_id)
                debounce_status = await cache.get(debounce_key)
                if debounce_status is None:
                    await background_tasks.enqueue(
                        "upload_crdt_snapshot_to_r2", file_id=file_id
                    )
                    await cache.set(
                        debounce_key,
                        "debounce",
                        ttl=self.debounce_ttl
                    )
                
            return doc
        
        except Exception as e:
            logger.error(f"Failed to process update or schedule upload for {project_id}/{file_id}: {e}")
            return None


crdt_handler = CrdtHandler(
    lorocrdt_text_container_id=LOROCRDT_TEXT_CONTAINER_ID,
    should_update_local_files=True,
    should_upload_to_r2=True
)
