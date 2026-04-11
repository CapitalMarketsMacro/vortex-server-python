from __future__ import annotations
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class MongoSettings(BaseModel):
    uri: str = "mongodb://MontuNobleNumbat2404:27017/"
    database: str = "Vortex"


class AdminSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8090
    secret_key: str = "vortex-admin-dev-secret"


class VortexSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VORTEX_",
        env_nested_delimiter="__",
    )

    port: int = 8080
    host: str = "0.0.0.0"
    log_level: str = "INFO"

    mongo: MongoSettings = MongoSettings()
    admin: AdminSettings = AdminSettings()


def load_settings() -> VortexSettings:
    return VortexSettings()
