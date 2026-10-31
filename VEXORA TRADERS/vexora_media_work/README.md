# 𝗩𝗘𝗫𝗢𝗥𝗔 𝗧𝗥𝗔𝗗𝗘𝗥𝗦 — expanded development build

𝗩𝗘𝗫𝗢𝗥𝗔 𝗧𝗥𝗔𝗗𝗘𝗥𝗦 is a trader-focused community application for sharing market ideas, strategies, chart screenshots, daily trading journals/results, joining discussion communities, finding contacts, and receiving curated signals from the app owner/authorized administrators. It is a community product, not a broker and it does not execute trades.

## Included in this build
- Language selection before signup email verification, email verification signup, password confirmation, password login, logout and session renewal (real email delivery needs SMTP credentials).
- Trader feed with discussion, strategy and daily-result posts, chart/image uploads, likes and comments.
- Discover members and add/remove contacts.
- Community directory, join/leave memberships, and a server-enforced rule-acceptance check before creating a community.
- Stored direct messages with WebSocket delivery, plus a persistent public Trader Lounge with live WebSocket broadcasts for signed-in members.
- Profile bio, avatar upload/removal, teal-accent dark/light themes and grouped privacy/accessibility settings.
- Dedicated VEXORA Admin AI Support page with an optional server-side AI provider and a limited built-in fallback; requests are authenticated and rate-limited.
- Expanded owner Control Room with overview metrics, quick links to the official signal desk and report moderation.
- Signals desk with market, direction, timeframe, entry, stop loss, targets, chart image and written analysis.
- Server-side admin allowlist for signal publishing and a moderation dashboard for reviewing reports, resolving reports and removing reported posts/signals/communities.
- User content reporting and account blocking; messaging endpoints check privacy and blocks.
- Security headers, CSRF checks for state-changing HTTP requests, Argon2 password hashing, rate limits for selected auth actions, and image type/size checks.
- Email-code password recovery with expiry, attempt limits, one-time use and forced re-login.
- WebAuthn/passkey registration, sign-in and passkey removal routes plus browser UI. The server stores public-key credentials only; it never receives fingerprint or Face ID data. Install the declared requirements and use HTTPS for passkeys.
- Optional Redis Pub/Sub to broadcast Trader Lounge events between multiple app instances.
- Dockerfile and Compose configuration for your hosting workflow.

## Local run
Python 3.11+ recommended. For local development, SQLite and the built-in fallback bot can be used without external services.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Open `http://127.0.0.1:8000`. The app is a web application, not an Android APK.

## Configure the app owner and administrators
Set `Bestura_TRADE_ADMINS` in `.env` to comma-separated registered usernames and/or email addresses, for example:

```env
Bestura_TRADE_ADMINS=ownername,admin@example.com
```
Restart the app after changing it. There is no public signup control that grants administrator permissions. This allowlist controls signal publishing and moderation access in this build. Keep `.env` private.

## Email verification
Configure `Bestura_SMTP_HOST`, `Bestura_SMTP_PORT`, `Bestura_SMTP_USER`, `Bestura_SMTP_PASSWORD`, and `Bestura_EMAIL_FROM`; set `Bestura_DEV_EMAIL_MODE=false` when real email is configured. Local development mode can display a test code and must not be used for public production.

## Live Trader Lounge and scaling

The Trader Lounge is a shared public room for signed-in members. Messages are saved in the database and history loads when reopening the room. WebSocket events update connected members in real time. Set `Bestura_REDIS_URL=redis://your-redis-host:6379/0` to enable cross-instance event broadcasts; if Redis is unavailable, each instance continues local chat but cross-instance delivery is not guaranteed. Before operating multiple app instances, also migrate from SQLite to PostgreSQL, use distributed rate limiting, durable shared file storage, health monitoring and load tests. Redis Pub/Sub is delivery fan-out, not durable message storage; the SQL database remains the message history. It is not a broker feed and does not execute trades.

## VEXORA Admin AI support and persistent member presence

The Trader Lounge stores both member messages and VEXORA Admin replies in the SQL database, so bot responses remain in history after refresh. To enable natural-language AI replies, set `Bestura_AI_API_KEY`, `Bestura_AI_BASE_URL` (an OpenAI-compatible `/v1` base URL), and `Bestura_AI_MODEL` in the private `.env`. If the provider is unavailable or no key is configured, the app uses a limited built-in fallback; this fallback is not a general-purpose AI. Keep API keys server-side and never place them in browser JavaScript. Bot replies are automated and should not be treated as financial advice.

Member presence uses a database-backed heartbeat every 30 seconds while a signed-in browser tab is active, including pages outside the Lounge, and refreshes when the user returns to the tab. Since all devices write to the shared database, presence is visible across devices and app workers. A user may remain shown online for up to about 90 seconds after closing a browser or losing connectivity; this is a last-seen approximation, not a guaranteed live socket count. Member profile pages show public bio, online state, post count and recent public posts; profiles are blocked when either member has blocked the other.


## Replit setup (minimal launch work)

This repository includes a `.replit` run/deployment configuration. Import the project into Replit from this ZIP or its Git repository; Replit should install dependencies from `requirements.txt` and use the configured Uvicorn command. The app binds to `0.0.0.0` and uses Replit's `PORT` when supplied.

Before publishing, add these values under **Replit → Secrets** (never commit real values to source control):

- `Bestura_ENV` = `production`
- `Bestura_SECRET_KEY` = a unique random secret of at least 32 characters
- `Bestura_COOKIE_SECURE` = `true` when served over HTTPS
- `Bestura_TRADE_ADMINS` = the owner/admin email address(es) or username(s), comma-separated
- `Bestura_DEV_EMAIL_MODE` = `false` for public production
- `Bestura_SMTP_HOST`, `Bestura_SMTP_PORT`, `Bestura_SMTP_USER`, `Bestura_SMTP_PASSWORD`, `Bestura_EMAIL_FROM` = your real email provider settings, so verification and password reset codes can be delivered
- `Bestura_DATABASE_URL` = a persistent PostgreSQL connection URL for production. The standard `DATABASE_URL` supplied by a hosting database is also accepted as a fallback. Do not rely on a local SQLite file for a production deployment if the host filesystem may be reset.
- `Bestura_PUBLIC_ORIGIN` = the exact public HTTPS origin, if passkeys are to be used
- `Bestura_AI_API_KEY` = optional; leave unset if you want the non-AI fallback bot. If enabled, also set `Bestura_AI_BASE_URL` and `Bestura_AI_MODEL` as appropriate. The key stays server-side and is never placed in browser code.

After adding Secrets, publish/deploy and verify `/health`, `/ready`, signup email delivery, login/logout, password reset, image uploads, chat, and the admin allowlist on the published URL. The website code and launch command are prepared, but the owner still has to supply valid service credentials, a persistent database, and a public deployment. Those cannot be safely fabricated or verified from this ZIP.

## Production Compose deployment

The Compose configuration uses PostgreSQL and a persistent upload volume, and refuses to start without a database password and a long session secret. Copy `.env.example` to `.env`, set unique strong values for `Bestura_SECRET_KEY` and `Bestura_POSTGRES_PASSWORD`, configure SMTP, and set `Bestura_PUBLIC_ORIGIN` to your real HTTPS origin. Set `Bestura_COOKIE_SECURE=true` only when requests are served through HTTPS; do not expose the service directly to the public internet without a TLS reverse proxy and appropriate host/network rules. To enable the AI bot, set `Bestura_AI_API_KEY` privately. Then run `docker compose up --build -d`. The AI provider, SMTP provider, domain/TLS, backups, and hosting account must be supplied by the operator; they cannot be provisioned from this source ZIP alone.

The Compose database is PostgreSQL; local development may continue to use SQLite. Alembic migration scaffolding and an initial schema baseline are included. For an existing database created by an older version, take a verified backup first, then review/stamp its schema against the baseline before using future migrations. Do not run a destructive downgrade on production data. The application retains startup table creation for backward compatibility with the original MVP; future schema changes should be delivered as reviewed Alembic revisions.

## Health checks, migrations and backups
- `GET /health` is a liveness endpoint; `GET /ready` verifies SQL connectivity and returns HTTP 503 when the database is unavailable.
- Set `Bestura_ENV=production` to make the app refuse startup without a fixed secret of at least 32 characters. Docker Compose enables this mode and binds port 8000 to localhost, so place a TLS reverse proxy in front of it.
- Alembic is configured with `alembic upgrade head`. Review the initial baseline and existing-database procedure before using it on a populated production database.
- On a host with Docker Compose and a configured private `.env`, run `ops/backup-postgres.sh` to create a timestamped compressed logical backup. Keep encrypted off-site copies and rehearse restoration; `ops/restore-postgres.sh` prompts before restoring and overwrites data.
- Backups and restore tests, monitoring, TLS/domain setup, AI-provider setup and SMTP delivery are operational tasks that require your own infrastructure and credentials; they cannot be truthfully marked complete from this offline source build.

## Tests
Run:

```bash
pytest -q
python -m py_compile app/main.py app/models.py app/database.py
node --check app/static/app.js
```

## Important production requirements (not silently claimed as complete)
This is an expanded, tested development build, not a guarantee of production readiness. Before public launch, complete a security review and load testing; configure HTTPS, a fixed random secret, production database migrations/backups, durable object storage for uploads, distributed rate limits and shared WebSocket/pub-sub for multiple app instances. Verify privacy/block behavior across all chat routes and clients, implement password recovery and account deletion workflows, notifications, robust community moderation, admin audit logs and operational monitoring. The current WebSocket service keeps live connections in process memory and therefore is not a multi-server chat deployment. The Trader Lounge is a real persisted single-instance live room, not a connection to an external third-party trading terminal or broker chat. Image uploads are stored on local disk; your host must preserve that storage or you must switch to object storage.

No live prices, broker account balances, or executable trades are provided. Signal and result content is user-published and can be inaccurate. Trading involves risk; nothing here guarantees financial outcomes or constitutes individualized financial advice. This build does not include video livestreaming; the product is focused on trader community and signals.

## Password recovery and device biometrics / passkeys

The app now has email-code password recovery and WebAuthn/passkey routes with registration/removal controls and a passkey sign-in option. Passkeys rely on the browser/operating system's credential manager; the site never reads or stores fingerprint or Face ID data. The `webauthn` package is declared in `requirements.txt`; install all requirements and restart the server to enable these routes. Passkeys require HTTPS (except browser-approved localhost development), a supported browser/device, and `Bestura_PUBLIC_ORIGIN` set to the exact public origin when deployed behind a proxy. Real device enrollment and sign-in still require testing on the actual Android/iOS devices and production domain; this development environment could not download/install the WebAuthn dependency because network access was unavailable, so end-to-end biometric/passkey verification has not been run here.

## Required deployment checklist

1. Generate a unique secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`; set `Bestura_SECRET_KEY` in your private `.env` and never publish it.
2. Configure SMTP credentials and `Bestura_DEV_EMAIL_MODE=false` so verification and reset codes go to real email. Never run with development codes enabled publicly.
3. Terminate HTTPS at your host/reverse proxy, set `Bestura_COOKIE_SECURE=true`, and set `Bestura_PUBLIC_ORIGIN=https://your-real-domain`.
4. Install the requirements (including `webauthn` and `redis`) and configure Redis if using multiple instances.
5. For real multi-instance production, move SQLite to PostgreSQL, use distributed rate limiting, shared object storage for uploads, database migrations/backups, logs/monitoring, security review and concurrent-user load tests.
6. Run the test commands below, then test registration, email delivery, password reset, sign-in/out, passkey enrollment, live chat, privacy/block rules and moderation on the deployed domain and devices.

## 𝗩𝗘𝗫𝗢𝗥𝗔 𝗧𝗥𝗔𝗗𝗘𝗥𝗦 community-management update

This build includes:
- Profile-level block and report/complaint actions.
- Owner/admin member controls (promote/remove admin and set member status to active, leave, vacation, or terminated).
- Admin markers on posts, signals, direct messages, and Lounge messages.
- Clickable external links in feed posts, signal analysis, and direct messages (opened in a new tab with safe link attributes).
- Direct-message voice-note recording/upload (up to 5 MB; browser microphone permission required; no video-call feature is added).
- A black Signals Desk card surface, refreshed navigation styling, and the “Traders Lounge” label.

### Initial owner/admin access
Set `Bestura_TRADE_ADMINS` in your hosting environment/Replit Secrets to a comma-separated list of the initial owner/admin usernames or email addresses. Only an already-authorized admin can promote additional members from their profile. Do not put this value in client-side code.

### Security and deployment notes
No application can honestly be described as “100% secure.” Review `PRODUCTION_READINESS_REPORT.md` and `REPLIT_LAUNCH_CHECKLIST.md`, use HTTPS, strong unique secrets, PostgreSQL and backups, and test the deployment before going live. Voice-note files are stored under `app/static/voice_notes`; configure persistent/private media storage and retention controls before handling sensitive recordings at scale. “Leave/vacation/terminated” are member-status labels in this build and do not constitute payroll or employment-system integration.


## Media uploads
See `MEDIA_UPLOAD_LIMITS.md` for supported formats, per-file limits, and hosting requirements for 200 MB videos. The product name displayed in the web UI is 𝗩𝗘𝗫𝗢𝗥𝗔 𝗧𝗥𝗔𝗗𝗘𝗥𝗦.
