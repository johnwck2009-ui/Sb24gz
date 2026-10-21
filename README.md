# Khmer Quiz Bot 🇰🇭

A Telegram quiz bot for Khmer-language multiple-choice quizzes, points, leaderboards, and daily challenges. Built with Python, `python-telegram-bot`, and SQLite.

## Features

- `/start` — welcome and account registration
- `/quiz` — random quiz question
- `/daily` — one daily challenge per user (UTC date)
- `/score` — your points and answered-question count
- `/leaderboard` — top players
- `/help` — command guide
- Admin commands: `/addquestion`, `/questions`, `/deletequestion`, `/stats`
- Button-based answers, duplicate-answer protection, and persistent SQLite scores
- Khmer sample questions included in `questions.json`

## Setup

1. Use Python 3.10 or newer.
2. Create a Telegram bot with [@BotFather](https://t.me/BotFather) and copy its token.
3. Copy `.env.example` to `.env`, then set `TELEGRAM_BOT_TOKEN`.
4. Set `ADMIN_USER_IDS` to comma-separated numeric Telegram user IDs for bot administrators. Keep this private.
5. Install dependencies and initialize the database:

   ```bash
   python -m venv .venv
   # macOS/Linux
   source .venv/bin/activate
   # Windows PowerShell: .venv\\Scripts\\Activate.ps1
   pip install -r requirements.txt
   python bot.py --init-db
   ```

6. Start the bot:

   ```bash
   python bot.py
   ```

The SQLite database (`quiz_bot.db`) is created locally and is ignored by Git. Never commit your bot token or `.env` file.

## Add questions

Admins can use `/addquestion` and then follow the prompts, or edit `questions.json` and restart the bot. Format:

```json
{
  "question": "សំណួរជាភាសាខ្មែរ?",
  "options": ["ជម្រើស ក", "ជម្រើស ខ", "ជម្រើស គ", "ជម្រើស ឃ"],
  "answer": 0,
  "explanation": "ការពន្យល់ខ្លីៗ"
}
```

`answer` is the zero-based index of the correct option. Admin `/addquestion` accepts four choices. `/questions` lists question IDs; `/deletequestion <id>` removes a question; `/stats` shows basic usage statistics.

## Notes

- Daily challenges reset at 00:00 UTC.
- Correct answers earn 1 point; each question can award points only once per user.
- This is a polling bot. Keep the Python process running or deploy it to a host that supports persistent processes and persistent disk for SQLite.
