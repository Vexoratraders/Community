# Market icon and chat attachment update

- Forex pair badges now use bundled SVG flag assets for EUR, USD, GBP, JPY, AUD, NZD, CAD, and CHF. This removes the external flag-host dependency that could leave the EUR/USD badge blank in embedded/mobile browsers.
- Gold/XAU uses a dedicated gold-bullion icon rather than the prior stylized coin/crest.
- Existing Bitcoin and Ethereum SVG icons remain in use; other supported crypto logos use their configured sources with a local generic fallback if a source fails.
- Chat attachment controls are compact, labelled buttons (“Attach” and “Voice note”) instead of oversized media controls.

## Validation performed
- `node --check app/static/app.js`
- `python -m compileall -q app`
- `pytest -q` — 4 tests passed

These checks validate syntax and the existing automated test suite. They do not replace visual testing in a deployed mobile browser.
