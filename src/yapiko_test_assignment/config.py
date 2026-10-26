from pathlib import Path
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="LLM_",
        extra="ignore",
    )

    base_url: str
    api_key: SecretStr
    model: str

    timeout: float = Field(default=20.0, gt=0)
    max_retries: int = Field(default=1, ge=0)
    temperature: float = Field(default=0.0, ge=0, le=2)

    menu_path: Path = Field(default=Path("data/menu.csv"), validation_alias="MENU_PATH")
    stop_list_path: Path = Field(
        default=Path("data/stop_list.json"), validation_alias="STOP_LIST_PATH"
    )

    mode: Literal["tools", "json", "json_schema", "md_json"] = "json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
