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

    # Команды /app и /link в группах
    GROUP_COMMANDS_ENABLED:  bool = True
    GROUP_COMMANDS_CHAT_IDS: list[int] = []   # пусто — во всех группах
    GROUP_COMMANDS_COOLDOWN: int = 30         # сек. между одинаковыми командами в одном чате

    # Через сколько секунд бот удаляет свой ответ в группе (0 — не удалять по таймеру).
    # Прошлый ответ на ту же команду удаляется всегда, когда приходит новый.
    GROUP_LINK_REPLY_TTL:    int = 120        # ответ на /link — 2 минуты
    GROUP_APP_REPLY_TTL:     int = 300        # ответ на /app — 5 минут

    # Антиспам
    THROTTLE_RATE:       int = 3      # макс. сообщений
    THROTTLE_PERIOD:     int = 2      # за N секунд
    THROTTLE_BAN_COUNT:  int = 20     # после N нарушений — временный бан
    THROTTLE_BAN_TTL:    int = 300    # на 5 минут

    # Прокси для проверки зеркал (например http://user:pass@host:port)
    HEALTHCHECK_PROXY:   str | None = None
    # Считать ответ 403 рабочим (Cloudflare часто так отвечает ботам при живом сайте).
    # Если заблокированные зеркала отвечают 403 — выключите.
    HEALTHCHECK_OK_403:  bool = True
    # Когда все активные зеркала упали — включить следующее рабочее по приоритету
    AUTO_SWITCH_ON_DOWN: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
