from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN:           str
    DATABASE_URL:        str       # postgresql+asyncpg://...
    REDIS_URL:           str = "redis://localhost:6379/0"
    ADMIN_IDS:           list[int] = []
    GROUP_ID:            int = 0
    MODERATION_ENABLED:  bool = False

    # Уведомлять админов о каждом новом пользователе
    NOTIFY_NEW_USERS:    bool = False

    # Удалять системные сообщения (вошёл/вышел/смена названия и т.д.)
    # во всех группах, где бот — администратор
    CLEAN_SERVICE_MESSAGES: bool = True

    # Антиспам
    THROTTLE_RATE:       int = 3      # макс. сообщений
    THROTTLE_PERIOD:     int = 2      # за N секунд
    THROTTLE_BAN_COUNT:  int = 20     # после N нарушений — временный бан
    THROTTLE_BAN_TTL:    int = 300    # на 5 минут

    # Прокси для проверки зеркал (например http://user:pass@host:port)
    HEALTHCHECK_PROXY:   str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
