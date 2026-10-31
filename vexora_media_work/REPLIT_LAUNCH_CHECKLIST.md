# 𝗩𝗘𝗫𝗢𝗥𝗔 𝗧𝗥𝗔𝗗𝗘𝗥𝗦 — Replit launch checklist

## Already included in the project
- FastAPI web app, frontend assets, SQLAlchemy models, tests and dependency list.
- Replit run/deployment configuration using the platform-provided `PORT`.
- Dedicated VEXORA Admin AI Support page and optional OpenAI-compatible AI integration; core website use does not depend on the AI API.
- Teal-accent dark/light themes, owner Control Room, community image posts and admin-only official signals/analysis.
- Health endpoints: `/health` (liveness) and `/ready` (database readiness).

## Add under Replit Secrets before publishing
Required for a production-style launch:
- `Bestura_ENV=production`
- `Bestura_SECRET_KEY` — unique random value, 32+ characters
- `Bestura_COOKIE_SECURE=true` — production requires HTTPS-only session cookies
- `Bestura_DATABASE_URL` — persistent PostgreSQL URL (or use the host's `DATABASE_URL`)
- `Bestura_DEV_EMAIL_MODE=false`
- `Bestura_SMTP_HOST`, `Bestura_SMTP_PORT`, `Bestura_SMTP_USER`, `Bestura_SMTP_PASSWORD`, `Bestura_EMAIL_FROM` — required; configure a verified sender. For Gmail, use an App Password (with 2-Step Verification), not your normal Google password.
- `Bestura_TRADE_ADMINS` — comma-separated owner/admin emails or usernames

Optional:
- `Bestura_AI_API_KEY`, `Bestura_AI_BASE_URL`, `Bestura_AI_MODEL`
- `Bestura_PUBLIC_ORIGIN` — exact HTTPS origin for passkeys
- `Bestura_REDIS_URL` — shared lounge events when running multiple instances

Production startup intentionally fails closed if the secret key, persistent PostgreSQL URL, or email provider configuration is missing. Set these Secrets before launching. Password recovery sends a short-lived reset code; for security, the app never emails users their existing password.

## Final smoke test
1. Open the published HTTPS URL and confirm `/health` responds.
2. Confirm `/ready` responds successfully with the configured database.
3. Register a test account and verify the email code arrives.
4. Sign in/out and verify password reset email delivery.
5. Test feed posts, image uploads, likes/comments, communities, contacts, direct messages and Trader Lounge.
6. Confirm a non-admin cannot publish official signals and an allowlisted admin can.
7. Test mobile layout, browser refresh, and session expiry behavior.
8. Confirm the database and uploaded images survive a redeploy/restart; configure persistent/shared file storage if the deployment filesystem is ephemeral, plus backups and monitoring.

Never commit `.env`, API keys, SMTP passwords, database credentials, or production secrets. AI is optional and must not be treated as financial advice. This is a launch checklist, not a substitute for security review and production smoke tests.
