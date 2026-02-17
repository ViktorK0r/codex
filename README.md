# Telegram Task Manager Bot

Минимальный Telegram-бот для командного управления задачами.

## Что умеет
- Создавать задачу с полями: **задача, исполнитель, срок, приоритет, теги**.
- Показывать все открытые задачи в чате.
- Показывать задачи, назначенные на текущего пользователя.
- Закрывать задачу.

## Быстрый старт

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Впишите TELEGRAM_BOT_TOKEN в .env
python bot.py
```

## Команды
- `/newtask Заголовок | @исполнитель | YYYY-MM-DD | low|medium|high | тег1,тег2`
- `/tasks`
- `/mytasks`
- `/done ID`
- `/help`

## Пример

```text
/newtask Подготовить релиз | @ivan | 2026-02-20 | high | backend,release
```

