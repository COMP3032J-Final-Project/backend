from aiocache.backends.redis import RedisCache
from aiocache.backends.memory import SimpleMemoryCache

import redis.asyncio as aioredis
from aiocache.serializers import NullSerializer
from .config import settings

url = settings.AIOCACHE_URL
if url.startswith("memory://"):
    cache = SimpleMemoryCache()
elif url.startswith("redis://"):
    redis_client = aioredis.Redis.from_url(url, decode_responses=False)
    cache = RedisCache(redis_client, namespace="main", serializer=NullSerializer())
else:
    raise Exception("Invalid settings.AIOCACHE_URL")






