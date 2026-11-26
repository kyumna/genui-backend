from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    allowed_origins: str = "http://localhost:3000"

    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    provider_order: str = "gemini,groq"
    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "openai/gpt-oss-120b"

    rate_limit_per_minute: int = 10
    save_rate_limit_per_minute: int = 20

    database_url: str | None = None

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
