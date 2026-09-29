from telegram import Bot
from telegram.error import TelegramError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def telegram_chat_id(user_id: str) -> int | None:
    """Telegram-linked users are identified by their Telegram user id, which
    doubles as their private chat id. Web-only users (e.g. "web_...") have no
    chat to message."""
    return int(user_id) if user_id.isdigit() else None


async def send_telegram_message(chat_id: int, text: str) -> bool:
    if not settings.TELEGRAM_BOT_TOKEN:
        return False
    try:
        async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(chat_id=chat_id, text=text)
        return True
    except TelegramError:
        logger.exception("failed to send telegram message", chat_id=chat_id)
        return False
