"""Khmer Quiz Bot — Telegram polling bot backed by SQLite."""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

load_dotenv()
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DB_PATH = os.getenv("DATABASE_PATH", "quiz_bot.db")
ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_USER_IDS", "").split(",")
    if value.strip().isdigit()
}
ADD_QUESTION, ADD_OPTION_1, ADD_OPTION_2, ADD_OPTION_3, ADD_OPTION_4, ADD_ANSWER, ADD_EXPLANATION = range(7)

WELCOME = (
    "សូមស្វាគមន៍មកកាន់ <b>Khmer Quiz Bot</b>! 🇰🇭\n\n"
    "សាកល្បងចំណេះដឹងរបស់អ្នក និងប្រមូលពិន្ទុ។\n"
    "ប្រើ /quiz ដើម្បីឆ្លើយសំណួរ ឬ /daily សម្រាប់សំណួរប្រចាំថ្ងៃ។\n\n"
    "ប្រើ /help ដើម្បីមើលពាក្យបញ្ជាទាំងអស់។"
)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT NOT NULL DEFAULT '',
                points INTEGER NOT NULL DEFAULT 0,
                answered_count INTEGER NOT NULL DEFAULT 0,
                joined_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                options_json TEXT NOT NULL,
                answer_index INTEGER NOT NULL CHECK(answer_index >= 0 AND answer_index <= 3),
                explanation TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                is_correct INTEGER NOT NULL,
                answered_at TEXT NOT NULL,
                quiz_date TEXT,
                UNIQUE(user_id, question_id, quiz_date),
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(question_id) REFERENCES questions(id)
            );
            CREATE INDEX IF NOT EXISTS idx_answers_user ON answers(user_id);
            CREATE INDEX IF NOT EXISTS idx_questions_active ON questions(active);
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        if count == 0:
            seed_questions(conn)


def seed_questions(conn: sqlite3.Connection) -> int:
    path = Path(__file__).with_name("questions.json")
    if not path.exists():
        return 0
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load questions.json: %s", exc)
        return 0
    inserted = 0
    for item in items:
        if valid_question(item.get("question"), item.get("options"), item.get("answer")):
            conn.execute(
                "INSERT INTO questions(question, options_json, answer_index, explanation, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    item["question"].strip(),
                    json.dumps(item["options"], ensure_ascii=False),
                    int(item["answer"]),
                    str(item.get("explanation", "")).strip(),
                    utc_now(),
                ),
            )
            inserted += 1
    return inserted


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def valid_question(question: Any, options: Any, answer: Any) -> bool:
    return (
        isinstance(question, str)
        and bool(question.strip())
        and isinstance(options, list)
        and len(options) == 4
        and all(isinstance(option, str) and option.strip() for option in options)
        and isinstance(answer, int)
        and not isinstance(answer, bool)
        and 0 <= answer <= 3
    )


def register_user(update: Update) -> None:
    user = update.effective_user
    if user is None:
        return
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO users(user_id, username, first_name, joined_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
            """,
            (user.id, user.username, user.first_name or "", utc_now()),
        )


def is_admin(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id in ADMIN_IDS)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    if update.message:
        await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>ពាក្យបញ្ជា</b>\n"
        "/start — ចាប់ផ្ដើមប្រើបុត\n"
        "/quiz — សំណួរចៃដន្យ\n"
        "/daily — សំណួរប្រចាំថ្ងៃ\n"
        "/score — ពិន្ទុរបស់អ្នក\n"
        "/leaderboard — តារាងអ្នកមានពិន្ទុខ្ពស់\n"
        "/help — ជំនួយ\n"
    )
    if is_admin(update):
        text += (
            "\n<b>ពាក្យបញ្ជាអ្នកគ្រប់គ្រង</b>\n"
            "/addquestion — បន្ថែមសំណួរតាមជំហាន\n"
            "/questions — បង្ហាញបញ្ជីសំណួរ\n"
            "/deletequestion ID — លុបសំណួរ\n"
            "/stats — ស្ថិតិបុត\n"
        )
    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)


def get_question(question_id: int | None = None, exclude_daily_date: str | None = None) -> dict[str, Any] | None:
    with connect_db() as conn:
        if question_id is not None:
            row = conn.execute(
                "SELECT * FROM questions WHERE id = ? AND active = 1", (question_id,)
            ).fetchone()
        elif exclude_daily_date:
            row = conn.execute(
                """
                SELECT q.* FROM questions q
                WHERE q.active = 1 AND q.id NOT IN (
                    SELECT question_id FROM answers WHERE quiz_date = ?
                )
                ORDER BY RANDOM() LIMIT 1
                """,
                (exclude_daily_date,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM questions WHERE active = 1 ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["options"] = json.loads(item.pop("options_json"))
    return item


async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE, daily: bool = False) -> None:
    register_user(update)
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return
    today = utc_date()
    if daily:
        with connect_db() as conn:
            existing = conn.execute(
                "SELECT question_id, is_correct FROM answers WHERE user_id = ? AND quiz_date = ?",
                (user.id, today),
            ).fetchone()
        if existing:
            result = "ត្រឹមត្រូវ ✅" if existing["is_correct"] else "មិនទាន់ត្រឹមត្រូវទេ 🙂"
            await message.reply_text(
                f"អ្នកបានឆ្លើយសំណួរប្រចាំថ្ងៃរួចហើយ ({result})។ ត្រឡប់មកវិញថ្ងៃស្អែក! 🌞"
            )
            return
        question = get_question(exclude_daily_date=today)
    else:
        question = get_question()
        if question:
            with connect_db() as conn:
                already = conn.execute(
                    "SELECT 1 FROM answers WHERE user_id = ? AND question_id = ? AND quiz_date IS NULL",
                    (user.id, question["id"]),
                ).fetchone()
            if already:
                question = get_question()
    if not question:
        await message.reply_text("មិនទាន់មានសំណួរទេ។ សូមត្រឡប់មកពេលក្រោយ! 🙏")
        return
    mode = "daily" if daily else "quiz"
    keyboard = [
        [InlineKeyboardButton(option, callback_data=f"answer:{mode}:{question['id']}:{index}")]
        for index, option in enumerate(question["options"])
    ]
    heading = "🌞 <b>សំណួរប្រចាំថ្ងៃ</b>\n\n" if daily else "🧠 <b>សំណួរចំណេះដឹង</b>\n\n"
    await message.reply_text(
        f"{heading}{question['question']}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_question(update, context, daily=False)


async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_question(update, context, daily=True)


async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None or not query.data:
        return
    await query.answer()
    try:
        _, mode, raw_question_id, raw_index = query.data.split(":")
        question_id, choice = int(raw_question_id), int(raw_index)
    except (ValueError, TypeError):
        await query.edit_message_text("សំណួរនេះមិនត្រឹមត្រូវទេ។ សូមសាកល្បងម្ដងទៀត។")
        return
    user = query.from_user
    today = utc_date()
    register_callback_user(user.id, user.username, user.first_name)
    quiz_date = today if mode == "daily" else None
    with connect_db() as conn:
        question = conn.execute(
            "SELECT * FROM questions WHERE id = ? AND active = 1", (question_id,)
        ).fetchone()
        if question is None:
            await query.edit_message_text("សំណួរនេះមិនមានទៀតទេ។")
            return
        prior = conn.execute(
            "SELECT is_correct FROM answers WHERE user_id = ? AND question_id = ? AND quiz_date IS ?",
            (user.id, question_id, quiz_date),
        ).fetchone()
        if prior:
            await query.edit_message_text("អ្នកបានឆ្លើយសំណួរនេះរួចហើយ។ ប្រើ /quiz សម្រាប់សំណួរថ្មី។")
            return
        options = json.loads(question["options_json"])
        if choice < 0 or choice >= len(options):
            await query.edit_message_text("ជម្រើសនេះមិនត្រឹមត្រូវទេ។")
            return
        correct = choice == question["answer_index"]
        conn.execute(
            "INSERT INTO answers(user_id, question_id, is_correct, answered_at, quiz_date) VALUES (?, ?, ?, ?, ?)",
            (user.id, question_id, int(correct), utc_now(), quiz_date),
        )
        conn.execute(
            "UPDATE users SET answered_count = answered_count + 1, points = points + ? WHERE user_id = ?",
            (1 if correct else 0, user.id),
        )
        score = conn.execute("SELECT points FROM users WHERE user_id = ?", (user.id,)).fetchone()["points"]
    explanation = (question["explanation"] or "").strip()
    if correct:
        result = "ត្រឹមត្រូវណាស់! 🎉 អ្នកទទួលបាន ១ ពិន្ទុ។"
    else:
        result = f"មិនត្រឹមត្រូវទេ 🙂 ចម្លើយត្រឹមត្រូវគឺ៖ {options[question['answer_index']]}"
    if explanation:
        result += f"\n\n💡 {explanation}"
    result += f"\n\n⭐ ពិន្ទុសរុបរបស់អ្នក៖ {score}"
    await query.edit_message_text(result)


def register_callback_user(user_id: int, username: str | None, first_name: str | None) -> None:
    with connect_db() as conn:
        conn.execute(
            """INSERT INTO users(user_id, username, first_name, joined_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username = excluded.username, first_name = excluded.first_name""",
            (user_id, username, first_name or "", utc_now()),
        )


async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    user = update.effective_user
    if not user or not update.effective_message:
        return
    with connect_db() as conn:
        row = conn.execute(
            "SELECT points, answered_count FROM users WHERE user_id = ?", (user.id,)
        ).fetchone()
    await update.effective_message.reply_text(
        f"🏅 <b>ពិន្ទុរបស់អ្នក</b>\n⭐ ពិន្ទុ៖ {row['points']}\n📝 បានឆ្លើយ៖ {row['answered_count']} សំណួរ",
        parse_mode=ParseMode.HTML,
    )


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT first_name, username, points FROM users ORDER BY points DESC, answered_count ASC, first_name COLLATE NOCASE LIMIT 10"
        ).fetchall()
    if not update.effective_message:
        return
    if not rows:
        await update.effective_message.reply_text("មិនទាន់មានអ្នកលេងទេ។ ចាប់ផ្ដើមជាមុនសិន!")
        return
    lines = ["🏆 <b>តារាងអ្នកមានពិន្ទុខ្ពស់</b>"]
    medals = ["🥇", "🥈", "🥉"]
    for index, row in enumerate(rows):
        name = ("@" + row["username"]) if row["username"] else (row["first_name"] or "អ្នកលេង")
        medal = medals[index] if index < 3 else f"{index + 1}."
        lines.append(f"{medal} {name} — ⭐ {row['points']}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def admin_only(update: Update) -> bool:
    if is_admin(update):
        return True
    if update.effective_message:
        await update.effective_message.reply_text("⛔ ពាក្យបញ្ជានេះសម្រាប់អ្នកគ្រប់គ្រងប៉ុណ្ណោះ។")
    return False


async def add_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await admin_only(update):
        return ConversationHandler.END
    if update.effective_message:
        await update.effective_message.reply_text("សូមផ្ញើអត្ថបទសំណួរ៖")
    return ADD_QUESTION


async def add_question_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_question"] = {"question": (update.effective_message.text or "").strip()}
    if update.effective_message:
        await update.effective_message.reply_text("ជម្រើសទី ១៖")
    return ADD_OPTION_1


async def add_option_1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_question"]["options"] = [(update.effective_message.text or "").strip()]
    if update.effective_message:
        await update.effective_message.reply_text("ជម្រើសទី ២៖")
    return ADD_OPTION_2


async def add_option_2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_question"]["options"].append((update.effective_message.text or "").strip())
    if update.effective_message:
        await update.effective_message.reply_text("ជម្រើសទី ៣៖")
    return ADD_OPTION_3


async def add_option_3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_question"]["options"].append((update.effective_message.text or "").strip())
    if update.effective_message:
        await update.effective_message.reply_text("ជម្រើសទី ៤៖")
    return ADD_OPTION_4


async def add_option_4(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_question"]["options"].append((update.effective_message.text or "").strip())
    if update.effective_message:
        await update.effective_message.reply_text(
            "លេខជម្រើសដែលត្រឹមត្រូវ? ផ្ញើលេខ 1, 2, 3 ឬ 4។"
        )
    return ADD_ANSWER


async def add_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.effective_message.text or "").strip()
    if raw not in {"1", "2", "3", "4"}:
        if update.effective_message:
            await update.effective_message.reply_text("សូមផ្ញើតែលេខ 1, 2, 3 ឬ 4។")
        return ADD_ANSWER
    context.user_data["new_question"]["answer"] = int(raw) - 1
    if update.effective_message:
        await update.effective_message.reply_text("ការពន្យល់ (ឬផ្ញើ - ដើម្បីរំលង)៖")
    return ADD_EXPLANATION


async def add_explanation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = context.user_data.pop("new_question", {})
    explanation = (update.effective_message.text or "").strip()
    if explanation == "-":
        explanation = ""
    if not valid_question(data.get("question"), data.get("options"), data.get("answer")):
        if update.effective_message:
            await update.effective_message.reply_text("ទិន្នន័យមិនត្រឹមត្រូវទេ។ សូមចាប់ផ្ដើមម្ដងទៀតដោយ /addquestion។")
        return ConversationHandler.END
    with connect_db() as conn:
        cursor = conn.execute(
            "INSERT INTO questions(question, options_json, answer_index, explanation, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                data["question"], json.dumps(data["options"], ensure_ascii=False),
                data["answer"], explanation, update.effective_user.id, utc_now()
            ),
        )
        question_id = cursor.lastrowid
    if update.effective_message:
        await update.effective_message.reply_text(f"✅ បានបន្ថែមសំណួរលេខ {question_id}។")
    return ConversationHandler.END


async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_question", None)
    if update.effective_message:
        await update.effective_message.reply_text("បានបោះបង់។")
    return ConversationHandler.END


async def questions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_only(update):
        return
    with connect_db() as conn:
        rows = conn.execute("SELECT id, question FROM questions WHERE active = 1 ORDER BY id DESC LIMIT 50").fetchall()
    if not update.effective_message:
        return
    if not rows:
        await update.effective_message.reply_text("មិនទាន់មានសំណួរទេ។")
        return
    lines = ["📚 <b>សំណួរដែលមាន (ចុងក្រោយ ៥០)</b>"]
    for row in rows:
        question = row["question"]
        if len(question) > 90:
            question = question[:87] + "..."
        lines.append(f"#{row['id']} — {question}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def delete_question_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_only(update):
        return
    if not context.args or not context.args[0].isdigit():
        if update.effective_message:
            await update.effective_message.reply_text("ប្រើ៖ /deletequestion ID")
        return
    question_id = int(context.args[0])
    with connect_db() as conn:
        cursor = conn.execute("UPDATE questions SET active = 0 WHERE id = ? AND active = 1", (question_id,))
    if update.effective_message:
        await update.effective_message.reply_text(
            "✅ បានលាក់សំណួរ។" if cursor.rowcount else "រកមិនឃើញសំណួរនោះទេ។"
        )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_only(update):
        return
    with connect_db() as conn:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        questions = conn.execute("SELECT COUNT(*) FROM questions WHERE active = 1").fetchone()[0]
        answers = conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
        correct = conn.execute("SELECT COUNT(*) FROM answers WHERE is_correct = 1").fetchone()[0]
    if update.effective_message:
        await update.effective_message.reply_text(
            f"📊 <b>ស្ថិតិបុត</b>\n👥 អ្នកលេង៖ {users}\n📚 សំណួរសកម្ម៖ {questions}\n📝 ចម្លើយសរុប៖ {answers}\n✅ ចម្លើយត្រឹមត្រូវ៖ {correct}",
            parse_mode=ParseMode.HTML,
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled bot error: %s", context.error, exc_info=context.error)


def build_application() -> Application:
    if not TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and add your token."
        )
    init_db()
    application = Application.builder().token(TOKEN).build()
    add_question_conversation = ConversationHandler(
        entry_points=[CommandHandler("addquestion", add_question_start)],
        states={
            ADD_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_text)],
            ADD_OPTION_1: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_option_1)],
            ADD_OPTION_2: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_option_2)],
            ADD_OPTION_3: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_option_3)],
            ADD_OPTION_4: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_option_4)],
            ADD_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_answer)],
            ADD_EXPLANATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_explanation)],
        },
        fallbacks=[CommandHandler("cancel", cancel_add)],
        allow_reentry=True,
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("daily", daily_command))
    application.add_handler(CommandHandler("score", score_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(add_question_conversation)
    application.add_handler(CommandHandler("questions", questions_command))
    application.add_handler(CommandHandler("deletequestion", delete_question_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CallbackQueryHandler(answer_callback, pattern=r"^answer:"))
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    parser = argparse.ArgumentParser(description="Khmer Quiz Telegram Bot")
    parser.add_argument("--init-db", action="store_true", help="Create the SQLite database and seed questions, then exit")
    args = parser.parse_args()
    if args.init_db:
        init_db()
        print(f"Database initialized at {DB_PATH}")
        return
    app = build_application()
    logger.info("Khmer Quiz Bot is starting (polling mode)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
