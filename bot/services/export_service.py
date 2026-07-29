"""
Генерирует CSV в памяти — не создаёт файлов на диске.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime

from bot.database.models import User


class ExportService:

    @staticmethod
    def users_to_csv(users: list[User]) -> io.BytesIO:
        """
        Возвращает BytesIO с CSV готовым к отправке как документ.
        Кодировка UTF-8 с BOM — корректно открывается в Excel.
        """
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

        # Заголовок
        writer.writerow([
            "ID", "Telegram ID", "Username", "Имя", "Фамилия",
            "Статус", "Источник", "Подписан",
            "Дата регистрации", "Последний вход",
        ])

        for user in users:
            writer.writerow([
                user.id,
                user.telegram_id,
                user.username or "",
                user.first_name or "",
                user.last_name or "",
                user.status,
                user.source or "direct",
                "Да" if user.is_subscribed else "Нет",
                _fmt(user.registered_at),
                _fmt(user.last_seen_at),
            ])

        # UTF-8 BOM для Excel
        bytes_io = io.BytesIO()
        bytes_io.write(b"\xef\xbb\xbf")
        bytes_io.write(output.getvalue().encode("utf-8"))
        bytes_io.seek(0)
        return bytes_io


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%d.%m.%Y %H:%M") if dt else ""