import os
import asyncio
import re
import secrets
import time
import hashlib
import smtplib
import json
import uuid
import mimetypes
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, desc, or_, and_
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .database import Base, engine, get_db
try:
    from redis.asyncio import Redis
except ImportError:
    Redis = None
try:
    from webauthn import generate_registration_options, verify_registration_response, generate_authentication_options, verify_authentication_response
    from webauthn.helpers import options_to_json
    from webauthn.helpers.structs import AuthenticatorSelectionCriteria, ResidentKeyRequirement, UserVerificationRequirement, PublicKeyCredentialDescriptor, AttestationConveyancePreference
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
    WEBAUTHN_AVAILABLE = True
except ImportError:
    WEBAUTHN_AVAILABLE = False
from .models import User, Post, Like, Comment, Community, Membership, DirectMessage, EmailVerification, Contact, TradeAnalysis, ContentReport, UserBlock, TraderLoungeMessage, PasskeyCredential, PasswordResetChallenge

BASE_DIR = Path(__file__).resolve().parent
SECRET_KEY = os.getenv("VEXORA_SECRET_KEY", "")
DEPLOYMENT_ENV = os.getenv("VEXORA_ENV", "production" if os.getenv("REPLIT_DEPLOYMENT") else "development").strip().lower()
IS_PRODUCTION = DEPLOYMENT_ENV == "production"
if len(SECRET_KEY) < 32:
    if DEPLOYMENT_ENV == "production":
        raise RuntimeError("VEXORA_SECRET_KEY must be set to a unique secret of at least 32 characters in production.")
    # Ephemeral fallback is for local development only; sessions reset after restart.
    SECRET_KEY = "LOCAL-ONLY-" + secrets.token_urlsafe(48)

COOKIE_SECURE = os.getenv("VEXORA_COOKIE_SECURE", "true" if IS_PRODUCTION else "false").lower() == "true"
if IS_PRODUCTION and not COOKIE_SECURE:
    raise RuntimeError("VEXORA_COOKIE_SECURE must be true in production.")
if IS_PRODUCTION and os.getenv("VEXORA_DEV_EMAIL_MODE", "false").lower() == "true":
    raise RuntimeError("VEXORA_DEV_EMAIL_MODE must be false in production.")

if IS_PRODUCTION:
    if engine.url.get_backend_name() == "sqlite":
        raise RuntimeError("Production requires a persistent PostgreSQL database. Set DATABASE_URL or VEXORA_DATABASE_URL in Replit Secrets.")
    if not os.getenv("VEXORA_SMTP_HOST", "").strip():
        raise RuntimeError("Production email is required. Set VEXORA_SMTP_HOST, VEXORA_SMTP_PORT, VEXORA_SMTP_USER, VEXORA_SMTP_PASSWORD, and VEXORA_EMAIL_FROM in Replit Secrets.")
    if not os.getenv("VEXORA_EMAIL_FROM", os.getenv("VEXORA_SMTP_USER", "")).strip():
        raise RuntimeError("Set VEXORA_EMAIL_FROM to a verified sender address in production.")

ph = PasswordHasher()
app = FastAPI(title="VEXORA", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="vexora_session",
                   same_site="lax", https_only=COOKIE_SECURE, max_age=60 * 60 * 24 * 7)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
Base.metadata.create_all(bind=engine)
# Backward-compatible migration for the reaction picker on existing installations.
try:
    from sqlalchemy import inspect, text
    if "likes" in inspect(engine).get_table_names():
        like_cols = {c["name"] for c in inspect(engine).get_columns("likes")}
        if "reaction" not in like_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE likes ADD COLUMN reaction VARCHAR(16) NOT NULL DEFAULT '❤️'"))
except Exception as migration_error:
    # Keep startup errors visible in logs; deployment migrations should be reviewed separately.
    print(f"VEXORA reaction-column migration notice: {migration_error}")
# Lightweight migration for earlier SQLite MVP databases. Production should use Alembic.
if engine.url.get_backend_name() == "sqlite":
    from sqlalchemy import text
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users)"))]
        if "email" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(254)"))
        if "email_verified" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 0"))
        if "avatar_url" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500) NOT NULL DEFAULT ''"))
        if "settings_json" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN settings_json TEXT NOT NULL DEFAULT '{}'"))
        if "last_seen_at" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN last_seen_at DATETIME"))
        post_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(posts)"))]
        if "image_url" not in post_cols:
            conn.execute(text("ALTER TABLE posts ADD COLUMN image_url VARCHAR(500) NOT NULL DEFAULT ''"))
        if "post_kind" not in post_cols:
            conn.execute(text("ALTER TABLE posts ADD COLUMN post_kind VARCHAR(24) NOT NULL DEFAULT 'discussion'"))
        if "result_label" not in post_cols:
            conn.execute(text("ALTER TABLE posts ADD COLUMN result_label VARCHAR(80) NOT NULL DEFAULT ''"))
        # Rename the earlier internal AI account without losing its lounge history.
        user_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users)"))]
        if "username" in user_cols:
            legacy_bot = conn.execute(text("SELECT id FROM users WHERE username = 'App_Name_Bot' LIMIT 1")).first()
            new_bot = conn.execute(text("SELECT id FROM users WHERE username = 'VEXORA_Admin' LIMIT 1")).first()
            if legacy_bot and not new_bot:
                conn.execute(text("UPDATE users SET username = 'VEXORA_Admin', bio = 'VEXORA Admin AI community assistant.' WHERE id = :uid"), {"uid": legacy_bot[0]})

# Best-effort compatibility rename for existing PostgreSQL and SQLite installations.
try:
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET username = 'VEXORA_Admin', bio = 'VEXORA Admin AI community assistant.' WHERE username = 'App_Name_Bot' AND NOT EXISTS (SELECT 1 FROM users WHERE username = 'VEXORA_Admin')"))
except Exception:
    # Fresh databases have no legacy bot row; startup should not fail on this optional rename.
    pass

# In-memory limiter is useful for local MVP only; use Redis/distributed rate limiting in production.
login_attempts = defaultdict(deque)
def limited(key: str, max_attempts: int = 8, window: int = 300) -> bool:
    now = time.time()
    q = login_attempts[key]
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= max_attempts:
        return True
    q.append(now)
    return False

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    response.headers["Cache-Control"] = "no-store"
    return response

def current_user(request: Request, db: Session) -> Optional[User]:
    uid = request.session.get("uid")
    if not isinstance(uid, int):
        return None
    return db.get(User, uid)

def require_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user

def csrf_ok(request: Request) -> bool:
    sent = request.headers.get("x-csrf-token", "")
    expected = request.session.get("csrf", "")
    return bool(sent and expected and secrets.compare_digest(sent, expected))

def json_error(message: str, status: int = 400):
    return JSONResponse({"error": message}, status_code=status)

def valid_uploaded_image_url(value: str) -> bool:
    """Only allow app-managed upload paths; never embed arbitrary remote URLs."""
    if not value:
        return True
    if not value.startswith("/static/uploads/") or "\\" in value or ".." in value:
        return False
    filename = value.removeprefix("/static/uploads/")
    return bool(filename and re.fullmatch(r"[A-Za-z0-9_.-]{1,180}", filename))

ONLINE_USER_IDS = set()

def get_user_role(user: Optional[User]) -> str:
    """Resolve privileged roles from server-controlled identity settings only.

    Never grant a role because a user knows or enters a shared password.
    The president and CEO must use their individually verified email addresses
    configured in deployment secrets. Admin promotion remains an explicit action.
    """
    if not user:
        return "MEMBER"
    email = (user.email or "").strip().lower()
    president_email = os.getenv("VEXORA_PRESIDENT_EMAIL", "").strip().lower()
    ceo_email = os.getenv("VEXORA_CEO_EMAIL", "").strip().lower()
    if president_email and email and secrets.compare_digest(email, president_email):
        return "VEXORA PRESIDENT"
    if ceo_email and email and secrets.compare_digest(email, ceo_email):
        return "VEXORA CEO"
    try:
        settings = json.loads(user.settings_json or "{}")
    except (ValueError, TypeError):
        settings = {}
    allowed = {x.strip().lower() for x in os.getenv("VEXORA_TRADE_ADMINS", "").split(",") if x.strip()}
    if settings.get("app_admin") or (email and email in allowed) or user.username.lower() in allowed:
        return "ADMINISTRATOR"
    return "MEMBER"


def safe_user(user: User):
    seen = user.last_seen_at
    if seen and seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    online = bool(seen and (datetime.now(timezone.utc) - seen).total_seconds() < 90)
    return {"id": user.id, "username": user.username, "email": user.email, "email_verified": bool(user.email_verified), "bio": user.bio, "avatar_url": user.avatar_url or "", "online": online, "role": get_user_role(user)}

def public_user_data(user: User):
    """Public directory/profile payload; never disclose email addresses."""
    data = safe_user(user)
    data.pop("email", None)
    data.pop("email_verified", None)
    return data

@app.get("/", response_class=HTMLResponse)
def home():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")

@app.post("/api/presence/heartbeat")
def presence_heartbeat(request: Request, db: Session = Depends(get_db)):
    """Refresh last-seen from any active app page/device, not only the Lounge."""
    if not csrf_ok(request):
        return json_error("Security token expired.", 403)
    user = current_user(request, db)
    if not user:
        return json_error("Please sign in.", 401)
    user.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return {"ok": True, "online": True, "last_seen_at": user.last_seen_at.replace(tzinfo=timezone.utc).isoformat()}

@app.get("/api/session")
def session_info(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return {"user": safe_user(user) if user else None, "csrf": request.session["csrf"]}

def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("Enter a valid email address.")
    return value

def send_verification_email(email: str, code: str, purpose: str = "verification") -> bool:
    host = os.getenv("VEXORA_SMTP_HOST", "").strip()
    if not host:
        return False
    msg = EmailMessage()
    msg["Subject"] = "Your VEXORA password reset code" if purpose == "password_reset" else "Your VEXORA verification code"
    sender = os.getenv("VEXORA_EMAIL_FROM", os.getenv("VEXORA_SMTP_USER", "")).strip()
    if not sender or "@" not in sender:
        raise RuntimeError("Set VEXORA_EMAIL_FROM to a valid sender address.")
    msg["From"] = sender
    msg["To"] = email
    label = "password reset" if purpose == "password_reset" else "email verification"
    msg.set_content(f"Your VEXORA {label} code is {code}. It expires in 10 minutes. If you did not request this, ignore this email.")
    port = int(os.getenv("VEXORA_SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=12) as server:
        server.ehlo()
        server.starttls(context=__import__("ssl").create_default_context())
        server.ehlo()
        user = os.getenv("VEXORA_SMTP_USER", "")
        password = os.getenv("VEXORA_SMTP_PASSWORD", "")
        if user:
            server.login(user, password)
        server.send_message(msg)
    return True

@app.get("/api/auth/captcha-config")
async def captcha_config():
    # Site key is public by design; the secret key is never sent to the browser.
    return {"site_key": os.getenv("VEXORA_TURNSTILE_SITE_KEY", "").strip()}

async def verify_turnstile(token: str, request: Request) -> bool:
    secret = os.getenv("VEXORA_TURNSTILE_SECRET_KEY", "").strip()
    if not secret:
        return not IS_PRODUCTION  # local tests/dev only; production startup refuses missing keys
    if not token or len(token) > 4096:
        return False
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={"secret": secret, "response": token,
                      "remoteip": request.client.host if request.client else ""},
            )
            response.raise_for_status()
            result = response.json()
            return result.get("success") is True
    except Exception:
        return False

@app.post("/api/auth/request-code")
async def request_code(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired. Refresh and try again.", 403)
    data = await request.json()
    try:
        email = normalize_email(str(data.get("email", "")))
    except ValueError as exc:
        return json_error(str(exc))
    language = str(data.get("language", "English"))
    supported_languages = {"English", "Arabic", "Bengali", "Chinese (Simplified)", "Chinese (Traditional)", "Danish", "Dutch", "Filipino", "Finnish", "French", "German", "Greek", "Gujarati", "Hausa", "Hebrew", "Hindi", "Hungarian", "Indonesian", "Italian", "Japanese", "Kannada", "Korean", "Malay", "Marathi", "Norwegian", "Persian", "Polish", "Portuguese", "Punjabi", "Romanian", "Russian", "Serbian", "Spanish", "Swahili", "Swedish", "Tamil", "Telugu", "Thai", "Turkish", "Ukrainian", "Urdu", "Vietnamese", "Yoruba", "Zulu"}
    if language not in supported_languages:
        return json_error("Choose a supported language before requesting your verification code.")
    request.session["signup_language"] = language
    ip = request.client.host if request.client else "unknown"
    if limited("code:" + ip, 5, 600) or limited("email:" + email, 4, 600):
        return json_error("Too many code requests. Wait a few minutes and try again.", 429)
    if db.scalar(select(User).where(User.email == email)):
        # Generic response avoids disclosing whether an email is already registered.
        return json_error("If this email can be registered, a verification code will be sent. Try signing in if you already have an account.", 409)
    code = f"{secrets.randbelow(1000000):06d}"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for old in db.scalars(select(EmailVerification).where(EmailVerification.email == email, EmailVerification.verified == False)).all():
        db.delete(old)
    challenge = EmailVerification(email=email, code_hash=hashlib.sha256(code.encode()).hexdigest(), expires_at=now + timedelta(minutes=10), attempts=0, verified=False)
    db.add(challenge); db.commit()
    try:
        delivered = send_verification_email(email, code)
    except Exception:
        db.delete(challenge); db.commit()
        return json_error("Email delivery failed. Check the server email settings and try again.", 503)
    if delivered:
        return {"ok": True, "message": "Verification code sent. Check your email."}
    if not IS_PRODUCTION and os.getenv("VEXORA_DEV_EMAIL_MODE", "false").lower() == "true":
        # Explicit local-only development convenience. Set false in production.
        return {"ok": True, "message": "Development mode: no email provider configured. Use the displayed test code.", "development_code": code}
    db.delete(challenge); db.commit()
    return json_error("Email service is not configured. Please contact the administrator.", 503)

@app.post("/api/auth/verify-code")
async def verify_code(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired. Refresh and try again.", 403)
    data = await request.json()
    try: email = normalize_email(str(data.get("email", "")))
    except ValueError as exc: return json_error(str(exc))
    code = str(data.get("code", "")).strip()
    challenge = db.scalar(select(EmailVerification).where(EmailVerification.email == email, EmailVerification.verified == False).order_by(desc(EmailVerification.created_at)))
    if not challenge: return json_error("Request a new verification code first.", 400)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if challenge.expires_at < now: return json_error("That code has expired. Request a new one.", 400)
    if challenge.attempts >= 5: return json_error("Too many incorrect attempts. Request a new code.", 429)
    challenge.attempts += 1
    if not re.fullmatch(r"\d{6}", code) or not secrets.compare_digest(challenge.code_hash, hashlib.sha256(code.encode()).hexdigest()):
        db.commit(); return json_error("Incorrect verification code.", 400)
    challenge.verified = True; db.commit()
    request.session["verified_signup_email"] = email
    return {"ok": True, "message": "Email verified. Now choose your username and password."}

@app.post("/api/auth/complete-signup")
async def complete_signup(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired. Refresh and try again.", 403)
    email = request.session.get("verified_signup_email")
    if not email: return json_error("Verify your email before creating an account.", 403)
    data = await request.json()
    captcha_token = str(data.get("captcha_token", ""))
    if not await verify_turnstile(captcha_token, request):
        return json_error("Please complete the I'm not a robot check and try again.", 400)
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not re.fullmatch(r"[A-Za-z0-9_]{3,24}", username): return json_error("Username must be 3–24 characters using letters, numbers, or underscores.")
    if username.casefold() in {"vexora_admin", "app_name_bot", "admin", "administrator", "support"}: return json_error("That username is reserved by VEXORA. Choose another username.")
    if len(password) < 12 or len(password) > 128: return json_error("Password must be 12–128 characters.")
    if password != str(data.get("confirm_password", "")): return json_error("Passwords do not match.")
    if db.scalar(select(User).where(User.username.ilike(username))): return json_error("That username is already taken.")
    if db.scalar(select(User).where(User.email == email)): return json_error("This email already has an account. Please sign in.", 409)
    challenge = db.scalar(select(EmailVerification).where(EmailVerification.email == email, EmailVerification.verified == True).order_by(desc(EmailVerification.created_at)))
    if not challenge or challenge.expires_at < datetime.now(timezone.utc).replace(tzinfo=None): return json_error("Verification expired. Request a new code.", 403)
    language = request.session.get("signup_language")
    if not language: return json_error("Choose your language and restart registration.", 403)
    user = User(username=username, email=email, email_verified=True, password_hash=ph.hash(password), settings_json=json.dumps({"language": language}))
    db.add(user); db.commit(); db.refresh(user)
    request.session.clear(); request.session["uid"] = user.id; request.session["csrf"] = secrets.token_urlsafe(32)
    return {"user": safe_user(user), "csrf": request.session["csrf"]}

@app.post("/api/login")
async def login(request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if limited(ip): return json_error("Too many login attempts. Wait a few minutes and try again.", 429)
    if not csrf_ok(request): return json_error("Security token expired. Refresh and try again.", 403)
    data = await request.json()
    identifier = str(data.get("email", data.get("username", ""))).strip()
    password = str(data.get("password", ""))
    user = db.scalar(select(User).where(or_(User.email == identifier.lower(), User.username.ilike(identifier))))
    try:
        valid = bool(user and ph.verify(user.password_hash, password))
    except (VerifyMismatchError, InvalidHashError):
        valid = False
    if not valid:
        return json_error("Invalid email/username or password.", 401)
    if user.email and not user.email_verified:
        return json_error("Please verify your email before signing in.", 403)
    if ph.check_needs_rehash(user.password_hash):
        user.password_hash = ph.hash(password)
        db.commit()
    request.session.clear()
    request.session["uid"] = user.id
    request.session["csrf"] = secrets.token_urlsafe(32)
    return {"user": safe_user(user), "csrf": request.session["csrf"]}

@app.post("/api/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    request.session.clear()
    return {"ok": True}

@app.post("/api/auth/password-reset/request")
async def request_password_reset(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired. Refresh and try again.", 403)
    data = await request.json()
    try: email = normalize_email(str(data.get("email", "")))
    except ValueError as exc: return json_error(str(exc))
    ip = request.client.host if request.client else "unknown"
    if limited("reset-ip:" + ip, 4, 600) or limited("reset-email:" + email, 3, 600):
        return json_error("Too many reset requests. Wait a few minutes and try again.", 429)
    user = db.scalar(select(User).where(User.email == email, User.email_verified == True))
    # Same response for known and unknown addresses prevents account enumeration.
    if user:
        code = f"{secrets.randbelow(1000000):06d}"
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for old in db.scalars(select(PasswordResetChallenge).where(PasswordResetChallenge.email == email, PasswordResetChallenge.used == False)).all():
            old.used = True
        db.add(PasswordResetChallenge(email=email, code_hash=hashlib.sha256(code.encode()).hexdigest(), expires_at=now + timedelta(minutes=10)))
        db.commit()
        try: delivered = send_verification_email(email, code, purpose="password_reset")
        except Exception: delivered = False
        if not delivered:
            if not IS_PRODUCTION and os.getenv("VEXORA_DEV_EMAIL_MODE", "false").lower() == "true":
                request.session["dev_reset_email"] = email
                request.session["dev_reset_code"] = code
                return {"ok": True, "message": "Development mode: use the test code.", "development_code": code}
            db.query(PasswordResetChallenge).filter(PasswordResetChallenge.email == email, PasswordResetChallenge.used == False).update({"used": True})
            db.commit()
            return json_error("Email service is not configured or delivery failed.", 503)
    return {"ok": True, "message": "If that verified account exists, a reset code has been sent."}

@app.post("/api/auth/password-reset/complete")
async def complete_password_reset(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired. Refresh and try again.", 403)
    data = await request.json()
    try: email = normalize_email(str(data.get("email", "")))
    except ValueError as exc: return json_error(str(exc))
    code = str(data.get("code", "")).strip()
    password = str(data.get("password", ""))
    if len(password) < 12 or len(password) > 128: return json_error("Password must be 12–128 characters.")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    challenge = db.scalar(select(PasswordResetChallenge).where(PasswordResetChallenge.email == email, PasswordResetChallenge.used == False).order_by(desc(PasswordResetChallenge.created_at)))
    if not challenge or challenge.expires_at < now: return json_error("Reset code expired or unavailable. Request a new one.", 400)
    if challenge.attempts >= 5: return json_error("Too many incorrect attempts. Request a new code.", 429)
    challenge.attempts += 1
    if not re.fullmatch(r"\d{6}", code) or not secrets.compare_digest(challenge.code_hash, hashlib.sha256(code.encode()).hexdigest()):
        db.commit(); return json_error("Incorrect reset code.", 400)
    user = db.scalar(select(User).where(User.email == email, User.email_verified == True))
    if not user: challenge.used = True; db.commit(); return json_error("Reset unavailable. Request a new code.", 400)
    user.password_hash = ph.hash(password); challenge.used = True; db.commit()
    # Force re-authentication on every browser by clearing this session.
    request.session.clear()
    request.session["csrf"] = secrets.token_urlsafe(32)
    return {"ok": True, "message": "Password reset successful. Sign in with your new password.", "csrf": request.session["csrf"]}

@app.get("/api/passkeys/status")
def passkey_status(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user: return json_error("Please sign in.", 401)
    return {"available": WEBAUTHN_AVAILABLE, "passkeys": [{"id": x.id, "label": x.label, "created_at": x.created_at.isoformat()} for x in db.scalars(select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)).all()]}

def webauthn_config(request: Request):
    origin = os.getenv("VEXORA_PUBLIC_ORIGIN", "").strip() or str(request.base_url).rstrip("/")
    from urllib.parse import urlparse
    parsed = urlparse(origin)
    return parsed.hostname or "localhost", origin

@app.post("/api/passkeys/register/options")
async def passkey_register_options(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired. Refresh and try again.", 403)
    if not WEBAUTHN_AVAILABLE: return json_error("Passkey support is not installed. Install the requirements and restart.", 503)
    user = current_user(request, db)
    if not user: return json_error("Please sign in first.", 401)
    rp_id, origin = webauthn_config(request)
    options = generate_registration_options(rp_id=rp_id, rp_name="VEXORA Traders", user_id=str(user.id).encode(), user_name=user.email or user.username, user_display_name=user.username, attestation=AttestationConveyancePreference.NONE, authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.PREFERRED, user_verification=UserVerificationRequirement.REQUIRED))
    request.session["passkey_register_challenge"] = bytes_to_base64url(options.challenge)
    request.session["passkey_register_origin"] = origin
    return json.loads(options_to_json(options))

@app.post("/api/passkeys/register/verify")
async def passkey_register_verify(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired. Refresh and try again.", 403)
    if not WEBAUTHN_AVAILABLE: return json_error("Passkey support is not installed.", 503)
    user = current_user(request, db)
    if not user: return json_error("Please sign in first.", 401)
    challenge = request.session.pop("passkey_register_challenge", None); origin = request.session.pop("passkey_register_origin", None)
    if not challenge or not origin: return json_error("Passkey registration expired. Try again.", 400)
    credential = await request.json()
    try:
        verified = verify_registration_response(credential=credential, expected_challenge=base64url_to_bytes(challenge), expected_rp_id=webauthn_config(request)[0], expected_origin=origin, require_user_verification=True)
    except Exception: return json_error("Could not verify this passkey. Try again on HTTPS with a supported device.", 400)
    cred_id = bytes_to_base64url(verified.credential_id)
    if db.scalar(select(PasskeyCredential).where(PasskeyCredential.credential_id == cred_id)):
        return json_error("This passkey is already registered.", 409)
    label = str(credential.get("label", "This device"))[:80] or "This device"
    db.add(PasskeyCredential(user_id=user.id, credential_id=cred_id, public_key=bytes_to_base64url(verified.credential_public_key), sign_count=verified.sign_count, label=label)); db.commit()
    return {"ok": True, "message": "Passkey registered on this device."}

@app.post("/api/passkeys/login/options")
async def passkey_login_options(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired. Refresh and try again.", 403)
    if not WEBAUTHN_AVAILABLE: return json_error("Passkey support is not installed.", 503)
    data = await request.json()
    try: email = normalize_email(str(data.get("email", "")))
    except ValueError as exc: return json_error(str(exc))
    user = db.scalar(select(User).where(User.email == email, User.email_verified == True))
    credentials = db.scalars(select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)).all() if user else []
    if not credentials: return json_error("No passkey is registered for this account.", 404)
    rp_id, origin = webauthn_config(request)
    options = generate_authentication_options(rp_id=rp_id, allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id)) for c in credentials], user_verification=UserVerificationRequirement.PREFERRED)
    request.session["passkey_login_challenge"] = bytes_to_base64url(options.challenge); request.session["passkey_login_origin"] = origin; request.session["passkey_login_user"] = user.id
    return json.loads(options_to_json(options))

@app.post("/api/passkeys/login/verify")
async def passkey_login_verify(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired. Refresh and try again.", 403)
    if not WEBAUTHN_AVAILABLE: return json_error("Passkey support is not installed.", 503)
    challenge = request.session.pop("passkey_login_challenge", None); origin = request.session.pop("passkey_login_origin", None); uid = request.session.pop("passkey_login_user", None)
    if not challenge or not origin or not isinstance(uid, int): return json_error("Passkey sign-in expired. Try again.", 400)
    credential = await request.json()
    cred_id = str(credential.get("id", ""))
    stored = db.scalar(select(PasskeyCredential).where(PasskeyCredential.credential_id == cred_id, PasskeyCredential.user_id == uid))
    if not stored: return json_error("Passkey was not recognized.", 401)
    try:
        verified = verify_authentication_response(credential=credential, expected_challenge=base64url_to_bytes(challenge), expected_rp_id=webauthn_config(request)[0], expected_origin=origin, credential_public_key=base64url_to_bytes(stored.public_key), credential_current_sign_count=stored.sign_count, require_user_verification=True)
    except Exception: return json_error("Passkey verification failed. Use your password or try again.", 401)
    stored.sign_count = verified.new_sign_count; db.commit(); user = db.get(User, uid)
    request.session.clear(); request.session["uid"] = user.id; request.session["csrf"] = secrets.token_urlsafe(32)
    return {"user": safe_user(user), "csrf": request.session["csrf"]}

@app.delete("/api/passkeys/{passkey_id}")
def delete_passkey(passkey_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    user = current_user(request, db)
    if not user: return json_error("Please sign in.", 401)
    credential = db.scalar(select(PasskeyCredential).where(PasskeyCredential.id == passkey_id, PasskeyCredential.user_id == user.id))
    if not credential: return json_error("Passkey not found.", 404)
    db.delete(credential); db.commit(); return {"ok": True, "message": "Passkey removed."}

@app.get("/api/feed")
def feed(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    posts = db.scalars(select(Post).options(joinedload(Post.author), joinedload(Post.likes), joinedload(Post.comments))
                       .order_by(desc(Post.created_at)).limit(50)).unique().all()
    result = []
    for p in posts:
        result.append({
            "id": p.id, "body": p.body, "image_url": getattr(p, "image_url", ""), "post_kind": getattr(p, "post_kind", "discussion"), "result_label": getattr(p, "result_label", ""), "author": (p.author.username if p.author and p.author.username and p.author.username != "[object Object]" else "VEXORA Trader"), "author_avatar": (p.author.avatar_url or "") if p.author else "",
            "created_at": p.created_at.isoformat(), "author_is_admin": is_app_admin(p.author), "likes": len(p.likes),
            "liked": bool(user and any(x.user_id == user.id for x in p.likes)),
            "my_reaction": next((x.reaction for x in p.likes if user and x.user_id == user.id), ""),
            "reaction_counts": {emoji: sum(1 for x in p.likes if (x.reaction or "❤️") == emoji) for emoji in ["❤️", "👍", "🔥", "💰", "🚀", "😂", "👀"]},
            "comments": [{"author": (c.author.username if c.author and c.author.username and c.author.username != "[object Object]" else "VEXORA Trader"), "body": c.body, "created_at": c.created_at.isoformat()}
                         for c in sorted(p.comments, key=lambda x: x.created_at)[:30]]
        })
    return {"posts": result}

@app.post("/api/posts")
async def create_post(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    user = current_user(request, db)
    if not user: return json_error("Please sign in to post.", 401)
    data = await request.json()
    body = str(data.get("body", "")).strip()
    if len(body) > 1200: return json_error("Post text must be 1200 characters or fewer.")
    kind = str(data.get("post_kind", "discussion"))
    if kind not in {"discussion", "strategy", "daily_result", "news"}: kind = "discussion"
    # News is an administrator-only feed post type. Enforce this on the server,
    # not just by hiding the option in the browser.
    if kind == "news" and not is_app_admin(user):
        return json_error("Only VEXORA administrators can publish news.", 403)
    image_url = str(data.get("image_url", "")).strip()[:500]
    if image_url and not valid_uploaded_image_url(image_url): return json_error("Images must be uploaded to VEXORA before they can be attached.")
    if not body and not image_url: return json_error("Add text or attach a picture before publishing.")
    result_label = str(data.get("result_label", "")).strip()[:80]
    post = Post(author_id=user.id, body=body, image_url=image_url, post_kind=kind, result_label=result_label)
    db.add(post); db.commit()
    return {"ok": True}

@app.post("/api/posts/image")
async def upload_post_image(request: Request, image: UploadFile = File(...), db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    if image.content_type not in ALLOWED_IMAGE_TYPES: return json_error("Use JPG, PNG, WEBP or GIF.")
    content = await image.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024: return json_error("Images may be up to 20 MB.")
    signatures = {"image/jpeg": content.startswith(b"\xff\xd8\xff"), "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"), "image/gif": content.startswith((b"GIF87a", b"GIF89a")), "image/webp": len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"}
    if not signatures.get(image.content_type, False): return json_error("That file is not a valid image.")
    filename = f"post_{me.id}_{uuid.uuid4().hex}{ALLOWED_IMAGE_TYPES[image.content_type]}"
    (UPLOAD_DIR / filename).write_bytes(content)
    return {"ok": True, "image_url": f"/static/uploads/{filename}"}

@app.post("/api/posts/video")
async def upload_post_video(request: Request, video: UploadFile = File(...), db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    mime = (video.content_type or "").split(";", 1)[0].lower()
    extensions = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}
    if mime not in extensions: return json_error("Use an MP4, WebM or MOV video.")
    chunks = []; total = 0; limit = 200 * 1024 * 1024
    while True:
        chunk = await video.read(1024 * 1024)
        if not chunk: break
        total += len(chunk)
        if total > limit: return json_error("Videos may be up to 200 MB.")
        chunks.append(chunk)
    content = b"".join(chunks)
    valid = (mime == "video/mp4" and len(content) > 12 and content[4:8] == b"ftyp") or (mime == "video/webm" and content.startswith(b"\x1aE\xdf\xa3")) or (mime == "video/quicktime" and len(content) > 12 and content[4:8] == b"ftyp")
    if not valid: return json_error("That file does not appear to be a valid supported video.")
    filename = f"post_{me.id}_{uuid.uuid4().hex}{extensions[mime]}"
    (UPLOAD_DIR / filename).write_bytes(content)
    return {"ok": True, "video_url": f"/static/uploads/{filename}"}

@app.post("/api/posts/{post_id}/like")
def toggle_like(post_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    user = current_user(request, db)
    if not user: return json_error("Please sign in to like posts.", 401)
    post = db.get(Post, post_id)
    if not post: return json_error("Post not found.", 404)
    like = db.scalar(select(Like).where(Like.user_id == user.id, Like.post_id == post_id))
    if like: db.delete(like)
    else: db.add(Like(user_id=user.id, post_id=post_id))
    db.commit()
    return {"ok": True}

@app.post("/api/posts/{post_id}/reaction")
async def set_post_reaction(post_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    user = current_user(request, db)
    if not user: return json_error("Please sign in to react to posts.", 401)
    if not db.get(Post, post_id): return json_error("Post not found.", 404)
    try: data = await request.json()
    except Exception: return json_error("Invalid request.")
    reaction = str(data.get("reaction", ""))
    allowed = {"❤️", "👍", "🔥", "💰", "🚀", "😂", "👀"}
    if reaction not in allowed: return json_error("Choose one of the available reactions.")
    existing = db.scalar(select(Like).where(Like.user_id == user.id, Like.post_id == post_id))
    if existing and existing.reaction == reaction:
        db.delete(existing)
    elif existing:
        existing.reaction = reaction
    else:
        db.add(Like(user_id=user.id, post_id=post_id, reaction=reaction))
    db.commit()
    return {"ok": True}

@app.post("/api/posts/{post_id}/comments")
async def comment(post_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    user = current_user(request, db)
    if not user: return json_error("Please sign in to comment.", 401)
    if not db.get(Post, post_id): return json_error("Post not found.", 404)
    data = await request.json()
    body = str(data.get("body", "")).strip()
    if not body or len(body) > 500: return json_error("Comment must contain 1–500 characters.")
    db.add(Comment(post_id=post_id, author_id=user.id, body=body)); db.commit()
    return {"ok": True}

@app.get("/api/communities")
def list_communities(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    rows = db.scalars(select(Community).options(joinedload(Community.memberships)).order_by(Community.name)).unique().all()
    return {"communities": [{"id": c.id, "name": c.name, "description": c.description,
                             "members": len(c.memberships),
                             "joined": bool(user and any(m.user_id == user.id for m in c.memberships))}
                            for c in rows]}

@app.post("/api/communities")
async def create_community(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    user = current_user(request, db)
    if not user: return json_error("Please sign in to create a community.", 401)
    data = await request.json()
    if data.get("accepted_rules") is not True: return json_error("You must accept the community rules before creating a community.")
    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    if not 3 <= len(name) <= 60: return json_error("Community name must be 3–60 characters.")
    if len(description) > 300: return json_error("Description is limited to 300 characters.")
    if db.scalar(select(Community).where(Community.name.ilike(name))):
        return json_error("That community name already exists.")
    community = Community(name=name, description=description, owner_id=user.id)
    db.add(community); db.flush()
    db.add(Membership(user_id=user.id, community_id=community.id)); db.commit()
    return {"ok": True}

@app.post("/api/communities/{community_id}/join")
def join_community(community_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    user = current_user(request, db)
    if not user: return json_error("Please sign in to join communities.", 401)
    community = db.get(Community, community_id)
    if not community: return json_error("Community not found.", 404)
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.community_id == community_id))
    if membership: db.delete(membership)
    else: db.add(Membership(user_id=user.id, community_id=community_id))
    db.commit()
    return {"ok": True}

@app.get("/api/users")
def users(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user: return json_error("Sign in to view members.", 401)
    blocked_ids = db.scalars(select(UserBlock.blocked_id).where(UserBlock.blocker_id == user.id)).all()
    blocked_by_ids = db.scalars(select(UserBlock.blocker_id).where(UserBlock.blocked_id == user.id)).all()
    hidden = set(blocked_ids + blocked_by_ids + [user.id])
    rows = db.scalars(select(User).where(User.id.not_in(hidden)).order_by(User.username).limit(100)).all()
    contact_ids = set(db.scalars(select(Contact.contact_user_id).where(Contact.user_id == user.id)).all())
    result = []
    for person in rows:
        item = public_user_data(person)
        item["is_contact"] = person.id in contact_ids
        try: item["show_online"] = json.loads(person.settings_json or "{}").get("show_online", True)
        except (ValueError, TypeError): item["show_online"] = True
        if not item["show_online"]: item["online"] = False
        result.append(item)
    return {"users": result}

@app.get("/api/messages/{other_user_id}")
def get_messages(other_user_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user: return json_error("Please sign in.", 401)
    other = db.get(User, other_user_id)
    if not other: return json_error("User not found.", 404)
    if db.scalar(select(UserBlock).where(or_(and_(UserBlock.blocker_id == user.id, UserBlock.blocked_id == other_user_id), and_(UserBlock.blocker_id == other_user_id, UserBlock.blocked_id == user.id)))):
        return json_error("Messages are unavailable between these accounts.", 403)
    try: prefs = json.loads(other.settings_json or "{}")
    except (ValueError, TypeError): prefs = {}
    if prefs.get("message_privacy", "contacts") == "nobody": return json_error("This trader is not accepting messages.", 403)
    if prefs.get("message_privacy", "contacts") == "contacts" and not db.scalar(select(Contact).where(Contact.user_id == other_user_id, Contact.contact_user_id == user.id)):
        return json_error("Add each other as contacts before viewing this conversation.", 403)
    rows = db.scalars(select(DirectMessage).where(
        or_(and_(DirectMessage.sender_id == user.id, DirectMessage.recipient_id == other_user_id),
            and_(DirectMessage.sender_id == other_user_id, DirectMessage.recipient_id == user.id))
    ).order_by(DirectMessage.created_at).limit(200)).all()
    return {"messages": [{"id": m.id, "sender_id": m.sender_id, "sender": m.sender.username,
                          "body": m.body, "is_admin": is_app_admin(m.sender), "created_at": m.created_at.isoformat()} for m in rows]}

@app.post("/api/messages/{other_user_id}")
async def send_message(other_user_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    user = current_user(request, db)
    if not user: return json_error("Please sign in.", 401)
    other = db.get(User, other_user_id)
    if not other: return json_error("User not found.", 404)
    if db.scalar(select(UserBlock).where(or_(and_(UserBlock.blocker_id == user.id, UserBlock.blocked_id == other_user_id), and_(UserBlock.blocker_id == other_user_id, UserBlock.blocked_id == user.id)))): return json_error("Messaging is unavailable between these accounts.", 403)
    try: prefs = json.loads(other.settings_json or "{}")
    except (ValueError, TypeError): prefs = {}
    if prefs.get("message_privacy", "contacts") == "nobody": return json_error("This trader is not accepting messages.", 403)
    if prefs.get("message_privacy", "contacts") == "contacts" and not db.scalar(select(Contact).where(Contact.user_id == other_user_id, Contact.contact_user_id == user.id)): return json_error("Add each other as contacts before messaging this trader.", 403)
    data = await request.json()
    body = str(data.get("body", "")).strip()
    if not body or len(body) > 1000: return json_error("Message must contain 1–1000 characters.")
    db.add(DirectMessage(sender_id=user.id, recipient_id=other_user_id, body=body)); db.commit()
    return {"ok": True}

@app.post("/api/messages/{other_user_id}/media")
async def upload_message_media(other_user_id: int, request: Request, media: UploadFile = File(...), db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    user = current_user(request, db)
    if not user: return json_error("Please sign in.", 401)
    other = db.get(User, other_user_id)
    if not other: return json_error("User not found.", 404)
    if db.scalar(select(UserBlock).where(or_(and_(UserBlock.blocker_id == user.id, UserBlock.blocked_id == other_user_id), and_(UserBlock.blocker_id == other_user_id, UserBlock.blocked_id == user.id)))):
        return json_error("Messaging is unavailable between these accounts.", 403)
    try: prefs = json.loads(other.settings_json or "{}")
    except (ValueError, TypeError): prefs = {}
    if prefs.get("message_privacy", "contacts") == "nobody": return json_error("This trader is not accepting messages.", 403)
    if prefs.get("message_privacy", "contacts") == "contacts" and not db.scalar(select(Contact).where(Contact.user_id == other_user_id, Contact.contact_user_id == user.id)):
        return json_error("Add each other as contacts before sending media.", 403)
    mime = (media.content_type or "").split(";", 1)[0].lower()
    image_exts = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
    video_exts = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}
    if mime in image_exts: limit = 20 * 1024 * 1024; ext = image_exts[mime]; kind = "image"
    elif mime in video_exts: limit = 200 * 1024 * 1024; ext = video_exts[mime]; kind = "video"
    else: return json_error("Send a JPG, PNG, WEBP, GIF image or MP4, WebM, MOV video.")
    chunks = []; total = 0
    while True:
        chunk = await media.read(1024 * 1024)
        if not chunk: break
        total += len(chunk)
        if total > limit: return json_error(f"{kind.title()}s may be up to {limit // (1024 * 1024)} MB.")
        chunks.append(chunk)
    content = b"".join(chunks)
    if kind == "image":
        signatures = {"image/jpeg": content.startswith(b"\xff\xd8\xff"), "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"), "image/gif": content.startswith((b"GIF87a", b"GIF89a")), "image/webp": len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"}
        valid = signatures.get(mime, False)
    else:
        valid = (mime in {"video/mp4", "video/quicktime"} and len(content) > 12 and content[4:8] == b"ftyp") or (mime == "video/webm" and content.startswith(b"\x1aE\xdf\xa3"))
    if not content or not valid: return json_error("The uploaded file is empty or has an invalid file signature.")
    folder = UPLOAD_DIR
    filename = f"dm_{user.id}_{uuid.uuid4().hex}{ext}"
    (folder / filename).write_bytes(content)
    url = f"/static/uploads/{filename}"
    db.add(DirectMessage(sender_id=user.id, recipient_id=other_user_id, body=f"[[media:{kind}:{url}]]")); db.commit()
    return {"ok": True, "url": url, "kind": kind}

@app.post("/api/ai/support")
async def ai_support(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired. Refresh and try again.", 403)
    user = current_user(request, db)
    if not user: return json_error("Please sign in to use VEXORA Admin support.", 401)
    if limited(f"ai-support:{user.id}", 12, 60): return json_error("VEXORA Admin is receiving requests too quickly. Please wait a minute.", 429)
    try: data = await request.json()
    except Exception: return json_error("Invalid request.")
    message = str(data.get("message", "")).strip()
    if not message or len(message) > 1200: return json_error("Write a message between 1 and 1,200 characters.")
    answer = await app_name_bot_reply(message, user.username, db)
    return {"ok": True, "assistant": "VEXORA Admin", "reply": answer, "provider_configured": bool(os.getenv("VEXORA_AI_API_KEY", "").strip())}


def fallback_bot_reply(message: str, username: str, previous: str = "") -> str:
    """Varied, transparent fallback when no AI provider is configured."""
    text = message.lower().strip()
    if any(x in text for x in ("hello", "hi ", "hey", "good morning", "good evening", "good afternoon")):
        options = [f"Hey @{username}! Welcome to the Lounge. What are you exploring today?", f"Hello @{username} 👋 Glad you're here. What's on your mind?", f"Welcome, @{username}! Feel free to share what you're working on."]
    elif any(x in text for x in ("bitcoin", "btc", "crypto")):
        options = ["For crypto, consider your timeframe, key levels and invalidation point. What setup are you watching?", "Crypto can move quickly. What's your thesis, and what would prove it wrong?", "Interesting. Check liquidity, volatility and position risk before acting—what chart are you studying?"]
    elif any(x in text for x in ("forex", "eurusd", "gbpusd", "xau", "gold", "market", "trade", "buy", "sell", "signal")):
        options = ["A useful setup outline includes context, entry trigger, invalidation and risk. Which timeframe are you using?", "Thanks for sharing. How are you thinking about downside risk and what would invalidate the idea?", "Let's break it down: trend or range, key levels and confirmation. What are you seeing on your chart?"]
    elif "how are you" in text:
        options = ["Doing well, thanks! I'm VEXORA Admin, here to help the community. How's your day going?", "All good here—ready to chat or help unpack a trading concept. How are you doing?"]
    elif any(x in text for x in ("help", "what", "how", "why", "?")):
        options = ["I can help explain general trading concepts and risk management. Could you share a little more detail so I can give a useful answer?", "Let's work through it together. Which part would you like to understand first?", "I can't see your chart unless you describe it, but I can help reason through the details. What are you looking at?"]
    else:
        options = [f"Thanks for sharing that, @{username}. What led you to that view?", "That's worth discussing. What do you think is the most important part?", "I hear you. Could you tell us a little more?", "Appreciate you adding to the conversation. What's your main takeaway?"]
    # Stable ordering plus previous-message avoidance, not Python's process-randomized hash.
    seed = sum((i + 1) * ord(ch) for i, ch in enumerate(text))
    ordered = options[seed % len(options):] + options[:seed % len(options)]
    for candidate in ordered:
        if candidate.casefold() != (previous or "").casefold():
            return candidate
    return ordered[0]

async def app_name_bot_reply(message: str, username: str, db: Session) -> str:
    """Use an optional OpenAI-compatible chat API; otherwise use the built-in fallback."""
    api_key = os.getenv("VEXORA_AI_API_KEY", "").strip()
    base_url = os.getenv("VEXORA_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("VEXORA_AI_MODEL", "gpt-4o-mini").strip()
    bot_user = db.scalar(select(User).where(User.username == "VEXORA_Admin"))
    recent_rows = db.scalars(select(TraderLoungeMessage).where(TraderLoungeMessage.author_id == bot_user.id).order_by(desc(TraderLoungeMessage.created_at)).limit(8)).all() if bot_user else []
    previous = recent_rows[0].body if recent_rows else ""
    recent_phrases = [row.body for row in recent_rows]
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=18.0) as client:
                response = await client.post(base_url + "/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, json={
                    "model": model, "temperature": 0.85, "max_tokens": 180,
                    "messages": [
                        {"role": "system", "content": "You are VEXORA Admin, the friendly, respectful and transparent AI community assistant inside VEXORA Traders. Reply naturally and briefly to the user's actual message. Vary wording and avoid repeating any recent reply listed below; ask a relevant follow-up when useful. You can explain general trading concepts, but never promise profit or present personalized financial advice. Never claim to be human. Recent replies to avoid repeating: " + json.dumps(recent_phrases, ensure_ascii=False)},
                        {"role": "user", "content": f"Member @{username} says: {message}"}
                    ]})
                response.raise_for_status()
                answer = str(response.json()["choices"][0]["message"]["content"]).strip()
                if answer and len(answer) <= 1000 and answer.casefold() not in {phrase.casefold() for phrase in recent_phrases}:
                    return answer
        except Exception:
            # Do not fail posting just because an external AI provider is unavailable.
            pass
    return fallback_bot_reply(message, username, previous)

def get_bot_user(db: Session) -> User:
    bot = db.scalar(select(User).where(User.username == "VEXORA_Admin"))
    if bot:
        return bot
    bot = User(username="VEXORA_Admin", email=None, email_verified=True,
               password_hash=ph.hash(secrets.token_urlsafe(48)), bio="VEXORA's automated community assistant.",
               avatar_url="", settings_json='{"show_online": false, "message_privacy": "nobody"}')
    db.add(bot)
    try:
        db.commit(); db.refresh(bot)
    except Exception:
        db.rollback()
        bot = db.scalar(select(User).where(User.username == "VEXORA_Admin"))
        if not bot: raise
    return bot

def save_bot_reply(db: Session, message: str, username: str) -> dict:
    bot = get_bot_user(db)
    # Async AI is handled by callers; this helper only stores already-created text.
    row = TraderLoungeMessage(author_id=bot.id, body=message)
    db.add(row); db.commit(); db.refresh(row)
    return {"type": "lounge_message", "id": row.id, "author_id": bot.id, "username": "VEXORA Admin", "is_admin": True, "avatar_url": "", "body": row.body, "created_at": row.created_at.isoformat()}

@app.get("/api/lounge/messages")
def get_lounge_messages(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        return json_error("Sign in to join the trader lounge.", 401)
    rows = db.scalars(select(TraderLoungeMessage).options(joinedload(TraderLoungeMessage.author)).order_by(desc(TraderLoungeMessage.created_at)).limit(100)).all()
    rows = list(reversed(rows))
    return {"messages": [{"id": m.id, "author_id": m.author_id, "username": "VEXORA Admin" if m.author.username == "VEXORA_Admin" else m.author.username, "avatar_url": m.author.avatar_url or "", "body": m.body, "is_admin": is_app_admin(m.author), "created_at": m.created_at.isoformat()} for m in rows]}

@app.post("/api/lounge/messages")
async def post_lounge_message(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request):
        return json_error("Security token expired. Refresh and try again.", 403)
    user = current_user(request, db)
    if not user:
        return json_error("Please sign in.", 401)
    if limited(f"lounge:{user.id}", 20, 60):
        return json_error("You're sending messages too quickly. Please wait a moment.", 429)
    data = await request.json()
    body = str(data.get("body", "")).strip()
    if not body or len(body) > 1000:
        return json_error("Message must contain 1–1000 characters.")
    row = TraderLoungeMessage(author_id=user.id, body=body)
    db.add(row); db.commit(); db.refresh(row)
    event = {"type": "lounge_message", "id": row.id, "author_id": user.id, "username": user.username, "is_admin": is_app_admin(user), "avatar_url": user.avatar_url or "", "body": row.body, "created_at": row.created_at.isoformat()}
    await lounge_realtime.broadcast(event)
    user.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
    reply = await app_name_bot_reply(body, user.username, db)
    bot_event = save_bot_reply(db, reply, user.username)
    await lounge_realtime.broadcast(bot_event)
    return {"ok": True, "message": event, "bot_message": bot_event}

@app.get("/api/profile")
def profile(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user: return json_error("Please sign in.", 401)
    return {"user": safe_user(user), "post_count": db.scalar(select(Post).where(Post.author_id == user.id).count()) if False else len(user.posts)}

@app.post("/api/profile")
async def update_profile(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    user = current_user(request, db)
    if not user: return json_error("Please sign in.", 401)
    data = await request.json()
    bio = str(data.get("bio", "")).strip()
    if len(bio) > 240: return json_error("Bio is limited to 240 characters.")
    user.bio = bio; db.commit()
    return {"ok": True, "user": safe_user(user)}

@app.get("/api/users/{user_id}/profile")
def public_profile(user_id: int, request: Request, db: Session = Depends(get_db)):
    viewer = current_user(request, db)
    if not viewer: return json_error("Please sign in to view member profiles.", 401)
    person = db.get(User, user_id)
    if not person: return json_error("Member not found.", 404)
    if person.id == viewer.id: return {"user": safe_user(person), "posts": [{"id": p.id, "body": p.body, "image_url": p.image_url or "", "post_kind": p.post_kind, "created_at": p.created_at.isoformat()} for p in db.scalars(select(Post).where(Post.author_id == person.id).order_by(desc(Post.created_at)).limit(50)).all()], "post_count": len(person.posts)}
    blocked = db.scalar(select(UserBlock).where(or_(and_(UserBlock.blocker_id == viewer.id, UserBlock.blocked_id == person.id), and_(UserBlock.blocker_id == person.id, UserBlock.blocked_id == viewer.id))))
    if blocked: return json_error("This profile is unavailable.", 403)
    try: prefs = json.loads(person.settings_json or "{}")
    except (ValueError, TypeError): prefs = {}
    posts = db.scalars(select(Post).where(Post.author_id == person.id).order_by(desc(Post.created_at)).limit(50)).all()
    public_user = public_user_data(person)
    public_user["is_admin"] = bool(prefs.get("app_admin"))
    public_user["member_status"] = str(prefs.get("member_status", "Active"))
    if not prefs.get("show_online", True): public_user["online"] = False
    return {"user": public_user, "viewer_is_admin": is_app_admin(viewer), "posts": [{"id": p.id, "body": p.body, "image_url": p.image_url or "", "post_kind": p.post_kind, "created_at": p.created_at.isoformat()} for p in posts], "post_count": len(person.posts)}

@app.get("/health")
def health():
    # Liveness endpoint: confirms the process is serving requests.
    return {"status": "ok", "service": "VEXORA"}

@app.get("/ready")
def readiness(db: Session = Depends(get_db)):
    # Readiness endpoint: checks the configured SQL database before routing traffic.
    from sqlalchemy import text
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database is not ready.")
    email_configured = bool(os.getenv("VEXORA_SMTP_HOST", "").strip() and os.getenv("VEXORA_EMAIL_FROM", os.getenv("VEXORA_SMTP_USER", "")).strip())
    if IS_PRODUCTION and not email_configured:
        raise HTTPException(status_code=503, detail="Email service is not configured. Set VEXORA_SMTP_HOST, VEXORA_SMTP_PORT, VEXORA_SMTP_USER, VEXORA_SMTP_PASSWORD, and VEXORA_EMAIL_FROM in deployment Secrets.")
    return {"status": "ready", "service": "VEXORA", "database": "ok", "email": "configured" if email_configured else "not_configured_development_only"}


# VEXORA social and realtime extensions
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}

@app.get("/api/contacts")
def list_contacts(request: Request, db: Session = Depends(get_db)):
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    ids = db.scalars(select(Contact.contact_user_id).where(Contact.user_id == me.id)).all()
    people = db.scalars(select(User).where(User.id.in_(ids))).all() if ids else []
    return {"contacts": [public_user_data(x) for x in people]}

@app.post("/api/contacts/{contact_user_id}")
def add_contact(contact_user_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    if contact_user_id == me.id: return json_error("You cannot add yourself.")
    target = db.get(User, contact_user_id)
    if not target: return json_error("User not found.", 404)
    try: target_prefs = json.loads(target.settings_json or "{}")
    except (ValueError, TypeError): target_prefs = {}
    if target_prefs.get("allow_friend_requests", True) is False: return json_error("This member is not accepting friend requests.", 403)
    existing = db.scalar(select(Contact).where(Contact.user_id == me.id, Contact.contact_user_id == contact_user_id))
    if not existing: db.add(Contact(user_id=me.id, contact_user_id=contact_user_id)); db.commit()
    return {"ok": True}

@app.delete("/api/contacts/{contact_user_id}")
def remove_contact(contact_user_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    row = db.scalar(select(Contact).where(Contact.user_id == me.id, Contact.contact_user_id == contact_user_id))
    if row: db.delete(row); db.commit()
    return {"ok": True}

@app.post("/api/profile/avatar")
async def upload_avatar(request: Request, avatar: UploadFile = File(...), db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    if avatar.content_type not in ALLOWED_IMAGE_TYPES: return json_error("Use JPG, PNG, WEBP or GIF.")
    content = await avatar.read(4 * 1024 * 1024 + 1)
    if len(content) > 4 * 1024 * 1024: return json_error("Avatar must be 4 MB or smaller.")
    # Basic signature checks prevent renamed non-image uploads.
    signatures = {"image/jpeg": content.startswith(b"\xff\xd8\xff"), "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"), "image/gif": content.startswith((b"GIF87a", b"GIF89a")), "image/webp": len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"}
    if not signatures.get(avatar.content_type, False): return json_error("That file is not a valid image.")
    filename = f"avatar_{me.id}_{uuid.uuid4().hex}{ALLOWED_IMAGE_TYPES[avatar.content_type]}"
    (UPLOAD_DIR / filename).write_bytes(content)
    old = (me.avatar_url or "").removeprefix("/static/uploads/")
    me.avatar_url = f"/static/uploads/{filename}"; db.commit()
    if old.startswith(f"avatar_{me.id}_"):
        try: (UPLOAD_DIR / old).unlink(missing_ok=True)
        except OSError: pass
    return {"ok": True, "avatar_url": me.avatar_url, "user": safe_user(me)}

@app.delete("/api/profile/avatar")
def delete_avatar(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    old = (me.avatar_url or "").removeprefix("/static/uploads/")
    me.avatar_url = ""; db.commit()
    if old.startswith(f"avatar_{me.id}_"):
        try: (UPLOAD_DIR / old).unlink(missing_ok=True)
        except OSError: pass
    return {"ok": True, "user": safe_user(me)}

@app.get("/api/settings")
def get_settings(request: Request, db: Session = Depends(get_db)):
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    try: settings = json.loads(me.settings_json or "{}")
    except (ValueError, TypeError): settings = {}
    defaults = {"theme": "dark", "notifications": True, "show_online": True, "language": "English", "read_receipts": True, "sound_effects": True, "email_updates": False, "message_privacy": "contacts", "allow_friend_requests": True, "reduced_motion": False, "media_autoplay": False, "compact_mode": False, "accent_color": "teal"}
    defaults.update(settings)
    return {"settings": defaults}

@app.put("/api/settings")
async def save_settings(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    data = await request.json()
    allowed = {"theme", "notifications", "show_online", "language", "read_receipts", "sound_effects", "email_updates", "message_privacy", "allow_friend_requests", "reduced_motion", "media_autoplay", "compact_mode", "accent_color"}
    try: old = json.loads(me.settings_json or "{}")
    except (ValueError, TypeError): old = {}
    for key in allowed:
        if key in data:
            if key == "theme" and data[key] not in {"dark", "light"}: return json_error("Choose dark or light theme.")
            if key == "accent_color" and data[key] not in {"teal", "blue", "purple", "green", "red", "orange", "pink"}: return json_error("Choose a supported accent color.")
            if key == "language" and data[key] not in {"English", "Arabic", "Bengali", "Chinese (Simplified)", "Chinese (Traditional)", "Danish", "Dutch", "Filipino", "Finnish", "French", "German", "Greek", "Gujarati", "Hausa", "Hebrew", "Hindi", "Hungarian", "Indonesian", "Italian", "Japanese", "Kannada", "Korean", "Malay", "Marathi", "Norwegian", "Persian", "Polish", "Portuguese", "Punjabi", "Romanian", "Russian", "Serbian", "Spanish", "Swahili", "Swedish", "Tamil", "Telugu", "Thai", "Turkish", "Ukrainian", "Urdu", "Vietnamese", "Yoruba", "Zulu"}: return json_error("Unsupported language.")
            if key in {"notifications", "show_online", "read_receipts", "sound_effects", "email_updates", "allow_friend_requests", "reduced_motion", "media_autoplay", "compact_mode", "accent_color"} and not isinstance(data[key], bool): return json_error("Invalid setting value.")
            if key == "message_privacy" and data[key] not in {"everyone", "contacts", "nobody"}: return json_error("Invalid message privacy setting.")
            old[key] = data[key]
    me.settings_json = json.dumps(old); db.commit()
    return {"ok": True, "settings": old}

class LiveConnections:
    def __init__(self): self.users = {}
    async def connect(self, uid, websocket):
        await websocket.accept(); self.users.setdefault(uid, set()).add(websocket)
    def disconnect(self, uid, websocket):
        self.users.get(uid, set()).discard(websocket)
        if not self.users.get(uid): self.users.pop(uid, None)
    async def send_user(self, uid, data):
        for ws in list(self.users.get(uid, set())):
            try: await ws.send_json(data)
            except Exception: self.disconnect(uid, ws)

realtime = LiveConnections()

class LoungeConnections:
    def __init__(self): self.connections = set()
    async def connect(self, websocket):
        await websocket.accept(); self.connections.add(websocket)
    def disconnect(self, websocket): self.connections.discard(websocket)
    async def broadcast_local(self, event):
        stale = []
        for ws in list(self.connections):
            try: await ws.send_json(event)
            except Exception: stale.append(ws)
        for ws in stale: self.disconnect(ws)
    async def broadcast(self, event):
        await self.broadcast_local(event)
        if redis_client is not None:
            try: await redis_client.publish("vexora:trader-lounge", json.dumps({"source": INSTANCE_ID, "event": event}))
            except Exception: pass  # Local chat remains available if Redis temporarily fails.

lounge_realtime = LoungeConnections()
INSTANCE_ID = uuid.uuid4().hex
redis_client = None
redis_listener_task = None

async def _listen_for_lounge_events():
    if redis_client is None: return
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("vexora:trader-lounge")
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message": continue
            try:
                payload = json.loads(message.get("data", "{}"))
                if payload.get("source") != INSTANCE_ID:
                    await lounge_realtime.broadcast_local(payload["event"])
            except (ValueError, KeyError, TypeError):
                continue
    finally:
        await pubsub.aclose()

async def start_shared_lounge():
    global redis_client, redis_listener_task
    redis_url = os.getenv("VEXORA_REDIS_URL", "").strip()
    if redis_url and Redis is not None:
        redis_client = Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)
        try:
            await redis_client.ping()
            redis_listener_task = asyncio.create_task(_listen_for_lounge_events())
        except Exception:
            await redis_client.aclose(); redis_client = None

async def stop_shared_lounge():
    global redis_client, redis_listener_task
    if redis_listener_task:
        redis_listener_task.cancel()
        try: await redis_listener_task
        except asyncio.CancelledError: pass
        redis_listener_task = None
    if redis_client:
        await redis_client.aclose(); redis_client = None

@asynccontextmanager
async def app_lifespan(application):
    await start_shared_lounge()
    try:
        yield
    finally:
        await stop_shared_lounge()

# Register a lifespan handler rather than deprecated startup/shutdown events.
app.router.lifespan_context = app_lifespan

@app.websocket("/ws/lounge")
async def websocket_lounge(websocket: WebSocket):
    uid = websocket.session.get("uid") if hasattr(websocket, "session") else None
    if not isinstance(uid, int):
        await websocket.close(code=4401); return
    origin = websocket.headers.get("origin", "")
    host = websocket.headers.get("host", "")
    if origin and host and origin.split("://", 1)[-1].split("/", 1)[0].lower() != host.lower():
        await websocket.close(code=4403); return
    db = next(get_db())
    try:
        user = db.get(User, uid)
        if not user:
            await websocket.close(code=4401); return
        user.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        await lounge_realtime.connect(websocket)
        ONLINE_USER_IDS.add(uid)
        await websocket.send_json({"type": "connected", "room": "trader-lounge"})
        while True:
            packet = await websocket.receive_json()
            user.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            if packet.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if packet.get("type") != "message": continue
            body = str(packet.get("body", "")).strip()
            if not body or len(body) > 1000: continue
            row = TraderLoungeMessage(author_id=uid, body=body)
            db.add(row); db.commit(); db.refresh(row)
            await lounge_realtime.broadcast({"type": "lounge_message", "id": row.id, "author_id": uid, "username": user.username, "avatar_url": user.avatar_url or "", "body": body, "created_at": row.created_at.isoformat()})
            reply = await app_name_bot_reply(body, user.username, db)
            bot_event = save_bot_reply(db, reply, user.username)
            await lounge_realtime.broadcast(bot_event)
    except WebSocketDisconnect:
        pass
    except Exception:
        try: await websocket.close(code=1011)
        except Exception: pass
    finally:
        lounge_realtime.disconnect(websocket)
        if not any(getattr(sock, "session", {}).get("uid") == uid for sock in lounge_realtime.connections): ONLINE_USER_IDS.discard(uid)
        db.close()

@app.websocket("/ws/chat/{other_user_id}")
async def websocket_chat(websocket: WebSocket, other_user_id: int):
    uid = websocket.session.get("uid") if hasattr(websocket, "session") else None
    if not isinstance(uid, int):
        await websocket.close(code=4401); return
    origin = websocket.headers.get("origin", "")
    host = websocket.headers.get("host", "")
    if origin and host and origin.split("://", 1)[-1].split("/", 1)[0].lower() != host.lower():
        await websocket.close(code=4403); return
    db = next(get_db())
    try:
        other = db.get(User, other_user_id)
        me = db.get(User, uid)
        if not other or not me: await websocket.close(code=4404); return
        blocked = db.scalar(select(UserBlock).where(or_(and_(UserBlock.blocker_id == uid, UserBlock.blocked_id == other_user_id), and_(UserBlock.blocker_id == other_user_id, UserBlock.blocked_id == uid))))
        if blocked: await websocket.close(code=4403); return
        try: other_prefs = json.loads(other.settings_json or "{}")
        except (ValueError, TypeError): other_prefs = {}
        if other_prefs.get("message_privacy", "contacts") == "nobody": await websocket.close(code=4403); return
        if other_prefs.get("message_privacy", "contacts") == "contacts" and not db.scalar(select(Contact).where(Contact.user_id == other_user_id, Contact.contact_user_id == uid)):
            await websocket.close(code=4403); return
        await realtime.connect(uid, websocket)
        await websocket.send_json({"type": "connected", "user_id": uid})
        while True:
            packet = await websocket.receive_json()
            user.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            if packet.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if packet.get("type") != "message": continue
            body = str(packet.get("body", "")).strip()
            if not body or len(body) > 1000: continue
            if limited(f"dm-ws:{uid}", 20, 60):
                await websocket.send_json({"type": "error", "message": "You're sending messages too quickly."}); continue
            row = DirectMessage(sender_id=uid, recipient_id=other_user_id, body=body); db.add(row); db.commit(); db.refresh(row)
            event = {"type": "message", "id": row.id, "sender_id": uid, "recipient_id": other_user_id, "body": body, "created_at": row.created_at.isoformat()}
            await realtime.send_user(uid, event); await realtime.send_user(other_user_id, event)
    except WebSocketDisconnect:
        pass
    except Exception:
        try: await websocket.close(code=1011)
        except Exception: pass
    finally:
        realtime.disconnect(uid, websocket); db.close()

# Trade analysis is a curated publishing area. Configure VEXORA_TRADE_ADMINS with
# comma-separated owner/admin emails or usernames in the server environment.
def can_publish_trade(user: Optional[User]) -> bool:
    if not user:
        return False
    allowed = {x.strip().lower() for x in os.getenv("VEXORA_TRADE_ADMINS", "").split(",") if x.strip()}
    return is_app_admin(user)

@app.get("/api/trades")
def list_trade_analyses(request: Request, db: Session = Depends(get_db)):
    rows = db.scalars(select(TradeAnalysis).options(joinedload(TradeAnalysis.author)).order_by(desc(TradeAnalysis.created_at)).limit(100)).all()
    return {"can_publish": can_publish_trade(current_user(request, db)), "trades": [{"id": r.id, "title": r.title, "market": r.market, "direction": r.direction, "timeframe": r.timeframe, "entry_price": r.entry_price, "stop_loss": r.stop_loss, "take_profit": r.take_profit, "analysis": r.analysis, "image_url": r.image_url, "created_at": r.created_at.isoformat(), "author": {**public_user_data(r.author), "is_admin": is_app_admin(r.author)}} for r in rows]}

@app.get("/api/trades/permissions")
def trade_permissions(request: Request, db: Session = Depends(get_db)):
    return {"can_publish": can_publish_trade(current_user(request, db))}

@app.post("/api/trades")
async def create_trade_analysis(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired. Refresh and try again.", 403)
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    if not can_publish_trade(me): return json_error("Only the configured VEXORA app owner or administrators can publish trade analysis.", 403)
    try: data = await request.json()
    except Exception: return json_error("Invalid request.")
    title = str(data.get("title", "")).strip()[:140]
    analysis = str(data.get("analysis", "")).strip()[:6000]
    if len(title) < 3 or len(analysis) < 10: return json_error("Add a title and at least 10 characters of analysis.")
    direction = str(data.get("direction", "Neutral"))
    if direction not in {"Buy", "Sell", "Neutral"}: return json_error("Invalid trade direction.")
    image_url = str(data.get("image_url", "")).strip()[:500]
    if not valid_uploaded_image_url(image_url): return json_error("Images must be uploaded to VEXORA before they can be attached.")
    row = TradeAnalysis(author_id=me.id, title=title, market=str(data.get("market", "")).strip()[:80], direction=direction, timeframe=str(data.get("timeframe", "")).strip()[:40], entry_price=str(data.get("entry_price", "")).strip()[:60], stop_loss=str(data.get("stop_loss", "")).strip()[:60], take_profit=str(data.get("take_profit", "")).strip()[:120], analysis=analysis, image_url=image_url)
    db.add(row); db.commit(); db.refresh(row)
    return {"ok": True, "id": row.id}

@app.post("/api/trades/image")
async def upload_trade_image(request: Request, image: UploadFile = File(...), db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    if not can_publish_trade(me): return json_error("Only the configured app owner or administrators can upload trade images.", 403)
    if image.content_type not in ALLOWED_IMAGE_TYPES: return json_error("Use JPG, PNG, WEBP or GIF.")
    content = await image.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024: return json_error("Trade image must be 8 MB or smaller.")
    signatures = {"image/jpeg": content.startswith(b"\xff\xd8\xff"), "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"), "image/gif": content.startswith((b"GIF87a", b"GIF89a")), "image/webp": len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"}
    if not signatures.get(image.content_type, False): return json_error("That file is not a valid image.")
    filename = f"trade_{me.id}_{uuid.uuid4().hex}{ALLOWED_IMAGE_TYPES[image.content_type]}"
    (UPLOAD_DIR / filename).write_bytes(content)
    return {"ok": True, "image_url": f"/static/uploads/{filename}"}


# Moderation and account safety features. Owner/admin identity is configured server-side only.
def is_app_admin(user: Optional[User]) -> bool:
    # Only the configured President/CEO and explicitly promoted administrators
    # receive administrative privileges. Ordinary signups never become admins.
    return get_user_role(user) in {"VEXORA PRESIDENT", "VEXORA CEO", "ADMINISTRATOR"}

@app.get("/api/admin/overview")
def admin_overview(request: Request, db: Session = Depends(get_db)):
    me = current_user(request, db)
    if not is_app_admin(me): return json_error("Administrator access required.", 403)
    open_reports = db.scalars(select(ContentReport).where(ContentReport.status == "open").order_by(desc(ContentReport.created_at)).limit(100)).all()
    return {"stats": {"users": db.query(User).count(), "posts": db.query(Post).count(), "communities": db.query(Community).count(), "signals": db.query(TradeAnalysis).count(), "open_reports": len(open_reports)},
            "reports": [{"id": r.id, "target_type": r.target_type, "target_id": r.target_id, "reason": r.reason, "details": r.details, "created_at": r.created_at.isoformat()} for r in open_reports]}

@app.post("/api/reports")
async def create_report(request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not me: return json_error("Please sign in to report content.", 401)
    try: data = await request.json()
    except Exception: return json_error("Invalid request.")
    target_type = str(data.get("target_type", "")); reason = str(data.get("reason", "Other"))[:80]
    try: target_id = int(data.get("target_id"))
    except (TypeError, ValueError): return json_error("Invalid report target.")
    if target_type not in {"post", "signal", "user", "community"}: return json_error("Invalid report target type.")
    target_model = {"post": Post, "signal": TradeAnalysis, "user": User, "community": Community}[target_type]
    if not db.get(target_model, target_id): return json_error("Content not found.", 404)
    duplicate = db.scalar(select(ContentReport).where(ContentReport.reporter_id == me.id, ContentReport.target_type == target_type, ContentReport.target_id == target_id, ContentReport.status == "open"))
    if duplicate: return {"ok": True, "message": "You already reported this item."}
    row = ContentReport(reporter_id=me.id, target_type=target_type, target_id=target_id, reason=reason, details=str(data.get("details", "")).strip()[:1000])
    db.add(row); db.commit()
    return {"ok": True}

@app.post("/api/users/{target_id}/block")
def block_user(target_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    if target_id == me.id or not db.get(User, target_id): return json_error("Invalid user.")
    if not db.scalar(select(UserBlock).where(UserBlock.blocker_id == me.id, UserBlock.blocked_id == target_id)):
        db.add(UserBlock(blocker_id=me.id, blocked_id=target_id)); db.commit()
    return {"ok": True}

@app.delete("/api/users/{target_id}/block")
def unblock_user(target_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not me: return json_error("Please sign in.", 401)
    row = db.scalar(select(UserBlock).where(UserBlock.blocker_id == me.id, UserBlock.blocked_id == target_id))
    if row: db.delete(row); db.commit()
    return {"ok": True}

@app.post("/api/admin/reports/{report_id}/resolve")
def resolve_report(report_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not is_app_admin(me): return json_error("Administrator access required.", 403)
    row = db.get(ContentReport, report_id)
    if not row: return json_error("Report not found.", 404)
    row.status = "resolved"; db.commit()
    return {"ok": True}

@app.delete("/api/admin/content/{target_type}/{target_id}")
def admin_remove_content(target_type: str, target_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not is_app_admin(me): return json_error("Administrator access required.", 403)
    model = {"post": Post, "signal": TradeAnalysis, "community": Community}.get(target_type)
    if not model: return json_error("Unsupported content type.")
    row = db.get(model, target_id)
    if not row: return json_error("Content not found.", 404)
    db.delete(row); db.commit()
    return {"ok": True}



@app.post("/api/admin/users/{target_id}/action")
async def admin_user_action(target_id: int, request: Request, db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    me = current_user(request, db)
    if not is_app_admin(me): return json_error("Administrator access required.", 403)
    target = db.get(User, target_id)
    if not target: return json_error("Member not found.", 404)
    if target.id == me.id: return json_error("You cannot change your own administrator status here.", 400)
    try: data = await request.json()
    except Exception: return json_error("Invalid request.")
    action = str(data.get("action", ""))
    try: settings = json.loads(target.settings_json or "{}")
    except (ValueError, TypeError): settings = {}
    if action == "promote_admin": settings["app_admin"] = True
    elif action == "remove_admin": settings.pop("app_admin", None)
    elif action in {"active", "leave", "vacation", "fired"}: settings["member_status"] = {"active":"Active", "leave":"On leave", "vacation":"On vacation", "fired":"Terminated"}[action]
    else: return json_error("Unsupported member action.")
    target.settings_json = json.dumps(settings)
    db.commit()
    return {"ok": True, "is_admin": bool(settings.get("app_admin")), "member_status": settings.get("member_status", "Active")}

@app.post("/api/messages/{other_user_id}/voice-note")
async def upload_voice_note(other_user_id: int, request: Request, audio: UploadFile = File(...), db: Session = Depends(get_db)):
    if not csrf_ok(request): return json_error("Security token expired.", 403)
    user = current_user(request, db)
    if not user: return json_error("Please sign in.", 401)
    other = db.get(User, other_user_id)
    if not other: return json_error("User not found.", 404)
    if db.scalar(select(UserBlock).where(or_(and_(UserBlock.blocker_id == user.id, UserBlock.blocked_id == other_user_id), and_(UserBlock.blocker_id == other_user_id, UserBlock.blocked_id == user.id)))):
        return json_error("Messaging is unavailable between these accounts.", 403)
    audio_type = (audio.content_type or "").split(";", 1)[0].strip().lower()
    if audio_type not in {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav"}:
        return json_error("Use a supported audio recording format.")
    content = await audio.read(6 * 1024 * 1024 + 1)
    if not content or len(content) > 6 * 1024 * 1024: return json_error("Voice notes may be up to 6 MB.")
    ext = {"audio/webm":"webm", "audio/ogg":"ogg", "audio/mp4":"m4a", "audio/mpeg":"mp3", "audio/wav":"wav", "audio/x-wav":"wav"}[audio_type]
    folder = BASE_DIR / "static" / "voice_notes"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    (folder / filename).write_bytes(content)
    url = f"/static/voice_notes/{filename}"
    db.add(DirectMessage(sender_id=user.id, recipient_id=other_user_id, body="[[voice-note:" + url + "]]"))
    db.commit()
    return {"ok": True, "url": url}

@app.get("/api/live/status")
def live_status():
    return {"available": False, "mode": "provider-required", "message": "Live chat can use WebSockets. Video broadcasting needs a configured WebRTC/streaming provider and TURN credentials."}
