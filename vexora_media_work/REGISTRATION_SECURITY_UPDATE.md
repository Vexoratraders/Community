# Registration security update

- Registration asks for a password and a confirmation password and rejects mismatches on the server.
- Registration requires a Cloudflare Turnstile challenge token, which is verified server-side.
- Configure `VEXORA_TURNSTILE_SITE_KEY` and `VEXORA_TURNSTILE_SECRET_KEY` in private deployment Secrets using real keys from Cloudflare Turnstile. Do not commit the secret key.
- Production startup refuses to run without both Turnstile keys.
- The President email is prefilled in `.env.example` as `vexoratraderscommunity@gmail.com`; set the same value in the live host private environment settings. The role is granted only to the account with that verified email. The CEO role uses `VEXORA_CEO_EMAIL`.
- Do not grant a privileged role based only on a password. Passwords are authentication credentials, not safe role identifiers. The password shared in chat should be changed before production use.

- Live deployment and real Cloudflare Turnstile keys are still required before production CAPTCHA verification can be confirmed.
