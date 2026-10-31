# VEXORA leadership role setup

Set these environment variables in your deployment's private Secrets/settings (not in source code):

- `VEXORA_PRESIDENT_EMAIL`: `vexoratraderscommunity@gmail.com` — the verified email address for the **VEXORA PRESIDENT** account.
- `VEXORA_CEO_EMAIL`: the verified email address of the account that should display **VEXORA CEO**.
- `VEXORA_TRADE_ADMINS`: optional comma-separated emails/usernames for explicitly authorized **ADMINISTRATOR** accounts.

The President and CEO roles are resolved from the account's verified email at sign-in/profile serialization time. Register/sign into the account using `vexoratraderscommunity@gmail.com`, and complete email verification. A password by itself must never grant a leadership role: anyone who learns it could take over the role. Do not put passwords in this file or commit them to source control.

Registration also uses Cloudflare Turnstile. Set VEXORA_TURNSTILE_SITE_KEY and VEXORA_TURNSTILE_SECRET_KEY in private deployment Secrets. The checkbox/token is verified server-side; a browser-only checkbox is not bot protection.

Ordinary public signups remain **MEMBER**. Do not make every signup an administrator: administrator permissions include moderation and other privileged actions. Promote only trusted accounts.

President email preconfigured in `.env.example`: `vexoratraderscommunity@gmail.com`. You still need to copy it into the live host private environment settings; editing this example file alone does not change a deployed site.
