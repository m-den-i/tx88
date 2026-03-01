from os import environ
from pydantic import BaseModel

from redislib import RedisReader


class SecretsData(BaseModel):
    login: str
    password: str


class StartupSettings:
    test: str

    async def load(self):
        self.test = environ.get("TEST", "empty")


class Settings:
    reader: RedisReader
    data: SecretsData
    

    def __init__(self, reader: RedisReader):
        self.reader = reader

    async def load(self) :
        await self.reader.init()
        self.data = SecretsData.model_validate(await self.reader.load())
        await self.reader.close()
