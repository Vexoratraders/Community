# 𝗩𝗘𝗫𝗢𝗥𝗔 𝗧𝗥𝗔𝗗𝗘𝗥𝗦 — Replit Quick Start

This project is prepared to import directly into Replit. You should not need to ask Replit AI to rebuild the app.

## 1) Import
1. In Replit, choose **Create Repl / Import from ZIP** (or upload this ZIP and open the project).
2. Keep the project files at the project root; `.replit` and `requirements.txt` must remain at the root.
3. Let Replit install the Python dependencies.

## 2) Add these Secrets before publishing
Open **Tools → Secrets** (or **Deployments → Secrets**, depending on the Replit UI) and add:

- `Bestura_ENV` = `production`
- `Bestura_SECRET_KEY` = a unique random secret at least 32 characters long. Generate one locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- `Bestura_COOKIE_SECURE` = `true`
- `Bestura_DEV_EMAIL_MODE` = `false`
- `Bestura_DATABASE_URL` = your persistent PostgreSQL connection URL. If Replit provides `DATABASE_URL`, the app can use that instead.
- `Bestura_SMTP_HOST` = your email provider's SMTP host
- `Bestura_SMTP_PORT` = `587` for typical STARTTLS SMTP
- `Bestura_SMTP_USER` = your email provider username/address
- `Bestura_SMTP_PASSWORD` = provider password or app password (for Gmail, use an App Password if available, not your normal Google password)
- `Bestura_EMAIL_FROM` = a sender address verified with your email provider
- `Bestura_TRADE_ADMINS` = your exact registered owner email or username; separate multiple entries with commas

Optional AI (leave out to use the limited built-in support fallback):
- `Bestura_AI_API_KEY` = your private API key
- `Bestura_AI_BASE_URL` = `https://api.openai.com/v1` for OpenAI
- `Bestura_AI_MODEL` = a model available to your API account

Never paste secrets into source files, public posts, or this chat. This ZIP contains no real credentials.

## 3) Run and publish
The `.replit` file contains the Uvicorn run and deployment commands. Run the app, then publish it. HTTPS must be enabled for secure cookies and passkeys.

## 4) Verify after publishing
- Open `/health` and `/ready` on the deployed URL.
- Register a test account and confirm the email code arrives.
- Test password reset using email.
- Test an image post and confirm uploaded images survive a redeploy/restart.
- Confirm a normal member cannot publish official signals and the allowlisted owner/admin can.
- Test messages, themes, mobile layout, and sign-out.

## Important
This project is prepared for import, but a ZIP cannot create your Replit database, provide SMTP credentials, verify your sender address, or publish the app on your behalf. Production startup intentionally requires valid secrets and services. Do not treat a successful build or unit tests as proof of zero vulnerabilities; perform the live checks above before inviting the public.
