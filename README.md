# Telegram Job Monitor Bot

A personal Telegram bot that monitors channels for job postings, matches them against your CV using AI-powered semantic similarity, and sends you alerts when good matches are found.

## Features

- **Multi-User Support** - Multiple authorized users can each upload their own CV and get personalized alerts
- **Channel Monitoring** - Listens to multiple Telegram channels simultaneously via MTProto
- **Smart Job Detection** - Classifies messages as job posts using keyword analysis
- **CV Matching** - Scores jobs against your CV using sentence-transformers (all-MiniLM-L6-v2)
- **Web Scraping** - Fetches additional job details from application URLs
- **Encrypted CV Storage** - Each user's CV is encrypted separately at rest using Fernet
- **Per-User Filters** - Each user can set their own keywords, location, remote preferences, seniority level, and threshold
- **Deduplication** - Avoids alerting you about the same job twice
- **Persistent State** - Survives restarts with SQLite database
- **Interactive Menu** - Button-based interface for easy bot control

## Tech Stack

| Component | Technology |
|-----------|------------|
| MTProto Client | Telethon |
| Bot Interface | aiogram 3.x |
| Database | SQLite + aiosqlite |
| Embeddings | sentence-transformers |
| Encryption | Fernet (cryptography) |
| Web Scraping | aiohttp + BeautifulSoup |

## Prerequisites

- Python 3.11+
- Telegram account
- Telegram API credentials (from [my.telegram.org](https://my.telegram.org))
- Bot token (from [@BotFather](https://t.me/BotFather))

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/cryoneth/job_bot_telegram.git
   cd job_bot_telegram
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   ```

   Edit `.env` with your credentials:
   ```env
   TELEGRAM_API_ID=your_api_id          # From my.telegram.org
   TELEGRAM_API_HASH=your_api_hash      # From my.telegram.org
   BOT_TOKEN=your_bot_token             # From @BotFather
   OWNER_USER_ID=your_user_id           # From @userinfobot
   AUTHORIZED_USERS=                    # Comma-separated user IDs (optional)
   CV_ENCRYPTION_KEY=                   # Auto-generated on first run
   MATCH_THRESHOLD=70                   # Default minimum score for alerts
   ```

5. **Run the bot**
   ```bash
   python main.py
   ```

   On first run, you'll be prompted to log in to your Telegram account (for channel monitoring).

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and setup instructions |
| `/help` | List all available commands |
| `/status` | Show bot status and statistics |
| `/setcv` | Upload your CV (text or file) |
| `/clearcv` | Delete stored CV |
| `/addchannel <link>` | Add a channel to monitor |
| `/removechannel <link>` | Stop monitoring a channel |
| `/listchannels` | Show all monitored channels |
| `/setthreshold <0-100>` | Set minimum match score for alerts |
| `/addkeyword <word>` | Add a required keyword |
| `/excludekeyword <word>` | Add an excluded keyword |
| `/setlocation <location>` | Set preferred location |
| `/setremote <yes/no/any>` | Set remote work preference |
| `/showfilters` | Display current filter settings |
| `/clearfilters` | Reset all filters |
| `/pause` | Pause monitoring |
| `/resume` | Resume monitoring |
| `/test` | Test with a sample job post |

## How It Works

```
Channel Message
      │
      ▼
┌─────────────────┐
│  Deduplication  │ ──▶ Skip if already processed
└─────────────────┘
      │
      ▼
┌─────────────────┐
│ URL Scraping    │ ──▶ Fetch job details from links
└─────────────────┘
      │
      ▼
┌─────────────────┐
│ Job Detection   │ ──▶ Skip if not a job post
└─────────────────┘
      │
      ▼
┌─────────────────┐
│ Field Extraction│ ──▶ Title, company, location, salary...
└─────────────────┘
      │
      ▼
┌─────────────────┐
│  CV Matching    │ ──▶ Semantic similarity + keywords
└─────────────────┘
      │
      ▼
┌─────────────────┐
│ Threshold Check │ ──▶ Skip if score < threshold
└─────────────────┘
      │
      ▼
    Alert!
```

## Match Scoring

The matching algorithm scores jobs from 0-100:

- **Semantic Similarity (0-60 points)** - Cosine similarity between CV and job embeddings
- **Keyword Bonus (0-25 points)** - +5 per matching skill keyword (max 5)
- **Rule Adjustments (-20 to +15 points)**
  - +10 if remote and user prefers remote
  - +5 if seniority level matches
  - -10 if excluded keyword found
  - -10 if location doesn't match preference

## Multi-User Support

The bot supports multiple authorized users, each with their own:
- **CV** - Stored separately as `cv_{user_id}.enc`
- **Filters** - Keywords, location, remote preference, seniority
- **Threshold** - Individual match score threshold

**Adding users:**
1. Get the user's Telegram ID (they can use [@userinfobot](https://t.me/userinfobot))
2. Add their ID to `AUTHORIZED_USERS` in `.env`: `AUTHORIZED_USERS=123456,789012`
3. Restart the bot

When a job is detected, the bot matches it against ALL users with CVs and sends personalized alerts to each user who scores above their threshold.

## Security

- Each user's CV is encrypted separately using Fernet symmetric encryption
- Encryption key stored in `.env` (not committed to git)
- Telegram session file excluded from git
- Database excluded from git
- All sensitive files listed in `.gitignore`

## Running as a Service

**Linux (systemd):**
```bash
sudo systemctl enable job-bot
sudo systemctl start job-bot
```

**macOS (launchd):**
```bash
launchctl load ~/Library/LaunchAgents/com.jobbot.plist
```

**Simple (tmux/screen):**
```bash
tmux new -s jobbot
python main.py
# Ctrl+B, D to detach
```

## License

MIT

## Contributing

Contributions welcome! Please open an issue or submit a pull request.
