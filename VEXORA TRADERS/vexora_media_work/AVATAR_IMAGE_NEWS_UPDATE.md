# VEXORA TRADERS — Avatar, Picture Posts, and Feed News Update

## Profile avatars
- Profile screen includes an `Upload / change avatar` file picker suitable for mobile browsers and photo galleries.
- Supported avatar formats: JPEG, PNG, WEBP, and GIF; maximum 4 MB.
- Uploading a replacement updates the profile avatar and removes the previous app-managed avatar file.
- `Remove avatar` clears the profile avatar and removes the old app-managed file.
- Avatar uploads require an authenticated session and CSRF token.

## Picture posts
- Feed composer accepts image selection from the device, with JPEG, PNG, WEBP, and GIF uploads up to 20 MB.
- Posts may contain text, a picture/video, or both; picture-only posts are supported.
- Media must be uploaded to the application; arbitrary remote image URLs are rejected.

## Administrator news
- President, CEO, and Administrator roles see an `Official news (administrator)` option in the feed composer.
- Publishing `news` is checked on the server; ordinary members receive HTTP 403.
- News posts are stored as normal feed posts, appear in the feed after publishing, and have a visually distinct card treatment.
- News can include an uploaded picture.

## Validation performed
- `node --check app/static/app.js`
- `python -m py_compile app/main.py`
- `pytest -q` — 4 tests passed, including avatar upload/removal, picture-only posts, admin-only news publishing, and feed visibility.

Live deployment and visual testing on a physical mobile phone were not performed in this environment. Deploy the project and test from an Android/iOS browser before production release.
