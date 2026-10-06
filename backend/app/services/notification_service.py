from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.permission_ask import PermissionAsk

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


async def send_permission_ask(chat_id: int, ask: PermissionAsk) -> bool:
    """Notify a user that a task is waiting on a permission decision, with
    inline buttons that answer it directly from this message. The callback
    data encodes everything telegram_bot.py's handler needs to resolve it:
    "ask:<id>:<decision>:<always 0|1>"."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return False

    what = ask.tool or ask.connector or ask.bucket
    text = (
        f"Task #{ask.task_id} wants to use: {what} (bucket: {ask.bucket}).\n"
        "Allow it?"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Allow once", callback_data=f"ask:{ask.id}:allow:0"),
                InlineKeyboardButton("Always allow", callback_data=f"ask:{ask.id}:allow:1"),
            ],
            [InlineKeyboardButton("Deny", callback_data=f"ask:{ask.id}:deny:0")],
        ]
    )
    try:
        async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        return True
    except TelegramError:
        logger.exception("failed to send permission ask", chat_id=chat_id, ask_id=ask.id)
        return False
