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

def get_cache_key_crdt_upload_r2_debounce(file_id: str | UUID):
    return f"crdt/debounce_r2_upload:{file_id}"

