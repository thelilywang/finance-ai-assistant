"""API 層專屬設定。與 src/config.py 分開：只有 API 進入點需要這些值。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    API_JWT_SECRET: str = ""  # 空值＝關閉驗證（僅本機開發），容器內由 main.py 擋掉
    API_JWT_ALG: str = "HS256"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8001

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
