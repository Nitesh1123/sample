from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    openai_api_key: str | None = None

    max_upload_size_mb: int = 25
    allowed_extensions: str = "pdf,jpg,jpeg,png"
    storage_dir: str = "/code/storage"

    class Config:
        env_file = ".env"

    @property
    def allowed_extensions_list(self) -> list[str]:
        return [e.strip().lower() for e in self.allowed_extensions.split(",")]


settings = Settings()
