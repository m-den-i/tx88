from dataclasses import dataclass
import json
from typing import Optional
import redis.asyncio as redis
import secrets_


@dataclass
class RedisReaderConfig:
    redis_url: str
    storage: str


class RedisReader:
    def __init__(self, config: Optional[RedisReaderConfig] = None):
        if config is None:
            config = RedisReaderConfig(**json.loads(secrets_.REDIS_READER_SETTINGS))
        self.config = config
    
    async def init(self) -> redis.Redis:
        self._client = await redis.from_url(self.config.redis_url)
        return await self.ping()

    async def load(self):
        res = await self._client.hgetall(self.config.storage)
        return {k.decode(): v.decode() for k, v in res.items()}

    async def close(self):
        await self._client.close()

    async def ping(self):
        return await self._client.ping()
