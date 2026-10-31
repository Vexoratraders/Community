# Community feature update notes

## Added in this archive
- Profile actions for blocking members and submitting user reports/complaints.
- Admin-only profile actions to promote/remove admin and update member-status labels.
- Server-side role checks based on the existing `Bestura_TRADE_ADMINS` allowlist plus stored `app_admin` role flag.
- Clickable external links in feed posts, trade analysis, and direct messages.
- Voice-note recording and upload in direct messages, limited to 5 MB and accepted audio MIME types. No video calls are included.
- Admin badges in feed posts, signals, direct messages, and Traders Lounge.
- Black Signals Desk cards and larger, clearer navigation styling.
- “Traders Lounge” rebrand and a working People-tab refresh.

## Important deployment/security caveats
- This is not a guarantee of perfect or 100% security. Keep dependencies patched, deploy HTTPS, set a unique secret, configure rate limiting and backups, and complete the production checklist.
- Admin promotion is server-authorized; initial owner identity must be set in `Bestura_TRADE_ADMINS` before using in-app promotion.
- Member status labels do not automatically suspend accounts or enforce employment decisions.
- Voice-note uploads are stored in the app's static directory in this build. For production, prefer persistent object storage with access control, retention/deletion policy, and malware/content monitoring as appropriate.
- Run the test suite before deployment; this package passed the included tests in the build environment.
