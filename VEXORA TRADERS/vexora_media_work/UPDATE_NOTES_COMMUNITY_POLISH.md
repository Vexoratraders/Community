# VEXORA Traders community polish update

## Included
- Fixed `[object Object]` rendering in names by safely normalizing display values; malformed/empty values display as `VEXORA Trader` instead of exposing a JavaScript object string. This does not invent a person's legal name. Members should use their own accurate profile identity.
- Added seven selectable post reactions (❤️, 👍, 🔥, 💰, 🚀, 😂, 👀), persistent reaction counts, and toggle/change behavior per member.
- Made the heart reaction red when selected and added selected styling for other reactions.
- Replaced the post-report prompt with a report form that asks for a reason and optional details before submitting to the existing moderation queue.
- Used member avatar URLs on feed posts and the post composer; existing profile avatar upload/remove support remains available.
- Added accent color preferences (teal, blue, purple, green, red, orange, pink) alongside dark/light theme settings.
- Added currency-pair flag badges for common forex pairs; existing asset icons remain for gold, Bitcoin, Ethereum, and other mapped assets.
- Made Buy signal badges solid green and Sell signal badges solid deep red.
- Refreshed direct-chat attachment and voice-note labels while preserving existing media and voice-note workflows.
- Added a backward-compatible `likes.reaction` column migration for existing databases.

## Verification performed
- `python -m py_compile app/main.py app/models.py` — passed.
- `node --check app/static/app.js` — passed.
- `pytest -q` — 4 tests passed.

## Important deployment note
These are code changes in the supplied project archive; they have not been deployed to your hosted VEXORA instance or tested against your production database/browser. Run your normal staging deployment and exercise signup, profile/avatar updates, feed reactions, reporting, messaging, and signal publishing before releasing. The app cannot truthfully verify that every production workflow works without access to that running environment.
