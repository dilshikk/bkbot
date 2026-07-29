from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN:           str
    DATABASE_URL:        str       # postgresql+asyncpg://...
    REDIS_URL:           str = "redis://localhost:6379/0"
    ADMIN_IDS:           list[int] = []
    GROUP_ID:            int = 0
    MODERATION_ENABLED:  bool = False

    # Антиспам
    THROTTLE_RATE:       int = 1      # макс. сообщений
    THROTTLE_PERIOD:     int = 2      # за N секунд
    THROTTLE_BAN_COUNT:  int = 20     # после N нарушений — временный бан
    THROTTLE_BAN_TTL:    int = 300    # на 5 минут

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
