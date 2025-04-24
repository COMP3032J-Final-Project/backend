from aiocache.backends.redis import RedisCache
from aiocache.backends.memory import SimpleMemoryCache
from uuid import UUID

import redis.asyncio as aioredis
from aiocache.serializers import NullSerializer
from .config import settings

cache_settings = {
    'namespace': "hivey",
    'serializer': NullSerializer(encoding=None)
}

url = settings.AIOCACHE_URL
# if url.startswith("memory://"):
#     cache = SimpleMemoryCache(**cache_settings)
if url.startswith("redis://"):
    redis_client = aioredis.Redis.from_url(url, decode_responses=False)
    cache = RedisCache(redis_client, **cache_settings)
else:
    raise Exception("Invalid settings.AIOCACHE_URL")


def get_cache_key_task_ppi(project_id: str | UUID):
    return f"task:perform_project_initialization:{project_id}/status"

def get_cache_key_crdt(file_id: str | UUID):
    return f"crdt:{file_id}"

def get_cache_key_new_file_lock(file_id: str | UUID):
    return f"crdt/new_file:{file_id}"

def get_cache_key_crdt_upload_r2_debounce(file_id: str | UUID):
    return f"crdt/debounce_r2_upload:{file_id}"

def get_cache_key_crdt_write_local_file_debounce(file_id: str | UUID):
    return f"crdt/debounce_write_local_file:{file_id}"


def get_cache_key_crdt_compile_project_pdf_debounce(file_id: str | UUID):
    return f"crdt/debounce_compile_project_pdf:{file_id}"

    
def get_cache_key_project_copmiled_pdf_url(project_id: str | UUID):
    return f"project/compiled_pdf:{project_id}"

# NOTE they are two coupled functions
def get_project_channel_name(project_id: str | UUID):
    return f"project/channel:{project_id}"
def get_project_id_from_channel_name(channel_name: str) -> str:
    return "".join(channel_name.split(":")[1:])

