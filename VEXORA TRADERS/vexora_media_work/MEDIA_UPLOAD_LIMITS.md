# 𝗩𝗘𝗫𝗢𝗥𝗔 𝗧𝗥𝗔𝗗𝗘𝗥𝗦 media upload limits

- Voice notes: up to 6 MB per recording.
- Private-message images: up to 20 MB each.
- Feed videos: up to 200 MB each.
- Private-message videos: up to 200 MB each.
- Supported images: JPEG, PNG, WEBP, GIF.
- Supported videos: MP4, WebM, MOV.

The limits are maximum sizes, not minimums: smaller files are allowed. Uploads are authenticated, CSRF-protected, MIME checked, and signature checked. Blocking is checked for private media uploads.

## Deployment note
The reverse proxy/hosting platform must accept request bodies of at least 210 MB and allow sufficient request timeouts, or 200 MB uploads may be rejected before the app receives them. For Nginx, configure `client_max_body_size 210m;` and suitable `client_body_timeout` / proxy timeouts. Ensure persistent storage for `app/static/uploads` and `app/static/voice_notes`, plus backups and malware/content moderation appropriate to your deployment. Large uploads currently buffer in application memory while validating; for high traffic, move to streaming/object storage and signed upload URLs.
