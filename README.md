# FlaX

FlaX is a Flask-based toolkit for interacting with the X API. It provides a minimal web UI and server-side helpers for creating Posts, managing subscriptions, and exploring timelines/search endpoints. This project targets the Pay Per Use beta program and has not been tested with Enterprise tier access. The frontend is intentionally bare-bones and the feature set is still evolving.

## Status

- Early, actively developed.
- Built for X API v2 Pay Per Use beta.
- Not tested with Enterprise tier.
- UI is minimal and focused on utility over polish.

## Requirements

- Python 3.10+
- SQLite (default) or any SQLAlchemy-supported database
- Dependencies listed in `requirements.txt`

## Dependencies

```
Flask==3.0.0
Flask-Migrate==4.0.5
Flask-SQLAlchemy==3.1.1
python-dotenv==1.0.1
requests==2.31.0
cryptography==42.0.5
Pillow==10.4.0
```

## Quickstart (macOS)

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy and edit environment variables:
   ```bash
   cp .env.example .env
   ```
4. Run migrations:
   ```bash
   export FLASK_APP=run.py
   flask db upgrade
   ```
5. Start the app:
   ```bash
   python run.py
   ```

## Quickstart (Windows)

1. Create and activate a virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
3. Copy and edit environment variables:
   ```powershell
   Copy-Item .env.example .env
   ```
4. Run migrations:
   ```powershell
   $env:FLASK_APP = "run.py"
   flask db upgrade
   ```
5. Start the app:
   ```powershell
   python run.py
   ```

## Environment configuration

The app uses `python-dotenv` to load `.env` automatically. At minimum, configure:

- `X_BEARER_TOKEN` - App-only bearer token
- `X_CLIENT_ID` - OAuth client ID
- `X_CLIENT_SECRET` - OAuth client secret
- `X_REDIRECT_URI` - OAuth callback URL (must match your X app settings)
- `X_ADMIN_USERNAMES` - Comma-separated usernames allowed to access admin features

Database and server options:

- `DATABASE_URL` - Defaults to `sqlite:///instance/app.db`
- `PORT` - Default is `5000`
- `SECRET_KEY` - Required for sessions

See `.env.example` for the full list.

## Running on a specific port

You can set a port in `.env`:

```
PORT=5015
```

Or run once with an inline override:

- macOS:
  ```bash
  PORT=5015 python run.py
  ```
- Windows (PowerShell):
  ```powershell
  $env:PORT = "5015"
  python run.py
  ```

## Debug mode

`run.py` starts Flask with `debug=True`. This is intended for local development.

For production deployment, use a WSGI server (gunicorn, waitress, etc.) and set debug to false in a separate entrypoint.

## Database and migrations

- Migrations are managed with Flask-Migrate.
- The project ships with a single initial migration that reflects the current models.
- If you change models, generate a new migration:
  ```bash
  flask db revision --autogenerate -m "describe change"
  flask db upgrade
  ```

## CLI commands

FlaX registers a small Click command group for X user lookups. Run these with
`flask` and the `x-api` group:

```bash
flask x-api get-user-by-username <username>
flask x-api get-users-by-usernames "user1,user2"
flask x-api get-user-by-id <user_id>
flask x-api get-users-by-ids "id1,id2"
flask x-api get-my-user
flask x-api search-users "<query>" --max-results 100 --next-token <token>
```

These commands use the same environment variables as the app. Make sure
`X_BEARER_TOKEN` is set before running them.

## Supported endpoints (UI)

**Activity**

- Create/list/update/delete activity subscriptions
- Activity stream helper (curl preview)

**Posts**

- Create/edit Post with media, polls, reply metadata, quote, community, geo, and nullcast flags
- Delete Post
- Repost and unrepost
- Reposts of me
- Post lookup by ID(s)
- Quote Tweets for a Post
- Recent and full-archive search
- Recent and full-archive counts
- User timeline and mentions
- Home timeline

**Likes**

- Like/Unlike a Post
- List likes for a user
- List users who liked a Post

**Users**

- User lookup by ID/username
- Multiple-user lookups
- User search
- Follow/Unfollow
- Mute/Unmute
- Block/Unblock

**Lists**

- List lookups, list Posts, list members/followers
- Follow/unfollow, add/remove members
- Pin/unpin lists

**Communities**

- Community lookup and search
- Community Posts

**Spaces**

- Space lookup and search
- Space Post lookups

**News**

- Search news stories
- Snapshot history

**Trends**

- Trends by location (WOEID)
- Snapshot history

**Media**

- Upload media
- Track uploaded media
- Copy media IDs for Post creation

**Usage**

- API usage snapshots and stats

## Notes

- The app is a continuing project with APIs being added incrementally.
- Some endpoints require OAuth user context; others work with bearer tokens.
- Feature availability depends on your X API access tier.
