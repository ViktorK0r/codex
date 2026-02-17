import logging
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "tasks.db")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


@dataclass
class TaskInput:
    title: str
    assignee: str
    due_date: str
    priority: str
    tags: str


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(get_conn()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                created_by_id INTEGER NOT NULL,
                created_by_username TEXT,
                title TEXT NOT NULL,
                assignee_username TEXT NOT NULL,
                due_date TEXT NOT NULL,
                priority TEXT NOT NULL,
                tags TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            )
            """
        )
        conn.commit()


def normalize_username(value: str) -> str:
    username = value.strip()
    return username if username.startswith("@") else f"@{username}"


def parse_task_input(raw: str) -> TaskInput:
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 5:
        raise ValueError(
            "Нужен формат: /newtask Заголовок | @исполнитель | YYYY-MM-DD | low|medium|high | тег1,тег2"
        )

    title, assignee, due_date, priority, tags = parts
    if not title:
        raise ValueError("Заголовок задачи не может быть пустым.")

    assignee = normalize_username(assignee)

    try:
        datetime.strptime(due_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Дата должна быть в формате YYYY-MM-DD.") from exc

    normalized_priority = priority.lower()
    if normalized_priority not in {"low", "medium", "high"}:
        raise ValueError("Приоритет: low, medium или high.")

    return TaskInput(
        title=title,
        assignee=assignee,
        due_date=due_date,
        priority=normalized_priority,
        tags=tags,
    )


def format_task_row(row: sqlite3.Row) -> str:
    tags = row["tags"] or "-"
    status = "✅ done" if row["status"] == "done" else "🟡 open"
    return (
        f"*#{row['id']}* {row['title']}\n"
        f"👤 {row['assignee_username']} | ⏰ {row['due_date']} | ⚡ {row['priority']}\n"
        f"🏷 {tags}\n"
        f"Статус: {status}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Привет! Я мини таск-менеджер для команды.\n\n"
        "Команды:\n"
        "• /newtask Заголовок | @исполнитель | YYYY-MM-DD | low|medium|high | тег1,тег2\n"
        "• /tasks — все открытые задачи\n"
        "• /mytasks — мои открытые задачи\n"
        "• /done ID — закрыть задачу\n"
        "• /help — подсказка"
    )
    await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def newtask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args).strip()
    if not raw:
        await update.message.reply_text(
            "Использование:\n/newtask Заголовок | @исполнитель | YYYY-MM-DD | low|medium|high | тег1,тег2"
        )
        return

    try:
        task = parse_task_input(raw)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    created_by = update.effective_user
    with closing(get_conn()) as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks (
                chat_id, created_by_id, created_by_username,
                title, assignee_username, due_date, priority, tags
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                update.effective_chat.id,
                created_by.id,
                normalize_username(created_by.username or f"user_{created_by.id}"),
                task.title,
                task.assignee,
                task.due_date,
                task.priority,
                task.tags,
            ),
        )
        conn.commit()
        task_id = cur.lastrowid

    await update.message.reply_text(f"Задача создана: #{task_id}")


def current_username(update: Update) -> Optional[str]:
    user = update.effective_user
    if user is None:
        return None
    if user.username:
        return normalize_username(user.username)
    return normalize_username(f"user_{user.id}")


async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE chat_id = ? AND status = 'open'
            ORDER BY due_date ASC, priority DESC, id DESC
            """,
            (update.effective_chat.id,),
        ).fetchall()

    if not rows:
        await update.message.reply_text("Открытых задач нет 🎉")
        return

    text = "\n\n".join(format_task_row(r) for r in rows)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def mytasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = current_username(update)
    if not username:
        await update.message.reply_text("Не удалось определить пользователя.")
        return

    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE chat_id = ? AND status = 'open' AND assignee_username = ?
            ORDER BY due_date ASC, priority DESC, id DESC
            """,
            (update.effective_chat.id, username),
        ).fetchall()

    if not rows:
        await update.message.reply_text("У вас нет открытых задач.")
        return

    text = "\n\n".join(format_task_row(r) for r in rows)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /done ID")
        return

    task_id = int(context.args[0])
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ? AND chat_id = ?",
            (task_id, update.effective_chat.id),
        ).fetchone()

        if not row:
            await update.message.reply_text("Задача не найдена.")
            return

        conn.execute(
            """
            UPDATE tasks
            SET status = 'done', completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task_id,),
        )
        conn.commit()

    await update.message.reply_text(f"Задача #{task_id} закрыта ✅")


def main() -> None:
    if not TOKEN:
        raise RuntimeError("Укажите TELEGRAM_BOT_TOKEN в .env")

    init_db()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("newtask", newtask))
    app.add_handler(CommandHandler("tasks", tasks))
    app.add_handler(CommandHandler("mytasks", mytasks))
    app.add_handler(CommandHandler("done", done))

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
