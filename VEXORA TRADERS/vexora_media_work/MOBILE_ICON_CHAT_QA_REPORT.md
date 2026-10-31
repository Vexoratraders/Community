# VEXORA TRADERS — Market Icon & Mobile Chat QA

## Changes included
- Forex pair icons use bundled local flag SVGs for EUR, USD, GBP, JPY, AUD, NZD, CAD and CHF.
- Each flag image has an error fallback, so a missing flag file does not leave an empty market badge.
- Gold/XAU uses the local gold-bullion icon.
- BTC and ETH use bundled local icons. SOL, XRP, DOGE, ADA, BNB, LINK and USDT now also use bundled local SVGs instead of third-party image URLs.
- Chat attachment controls remain compact and responsive for narrow screens.
- President email and registration-security configuration from the supplied project are preserved; real Turnstile keys and deployment secrets still need to be set privately by the operator.

## Checks completed in the local test environment
- `python -m compileall -q app` — passed.
- `node --check app/static/app.js` — passed.
- `pytest -q` — 4 passed.
- Local HTTP checks — `/`, `/health`, `/ready`, all 8 bundled forex flags and all 12 market SVG assets returned HTTP 200 with non-empty bodies.
- JavaScript market-badge checks — EUR/USD, GBP/USD, USD/JPY, XAU/USD, GOLD, BTC, ETH, SOL, XRP, DOGE, ADA, BNB, LINK and USDT all mapped to the expected local icon paths.

## Verification boundary
A headless Chromium attempt to open the local app was blocked by the execution environment (`ERR_BLOCKED_BY_ADMINISTRATOR`). Therefore this report does not claim a visual browser session or testing on the owner's live phone/site. Live deployment and on-device verification still require the deployed URL and hosting access.
