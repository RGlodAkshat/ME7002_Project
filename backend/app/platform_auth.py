"""Credential and cookie sessions, shared by HTTP and integration interfaces."""
import hashlib
import hmac
import secrets
import time
from threading import Lock
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session, object_session

from .config import get_settings
from .db import get_db
from .platform_models import LoginSession, User, UserQualification

COOKIE = "manufacturing_session"
LOGIN_FAILURES: dict[tuple[str, str], list[float]] = {}
LOGIN_LOCK = Lock()


def check_login_rate(ip: str, email: str) -> None:
    with LOGIN_LOCK:
        now = time.monotonic()
        failures = [timestamp for timestamp in LOGIN_FAILURES.get((ip, email), []) if timestamp > now - 60]
        LOGIN_FAILURES[(ip, email)] = failures
        if len(failures) >= 5:
            raise HTTPException(429, "Too many sign-in attempts. Try again in a minute.")


def record_login(ip: str, email: str, success: bool) -> None:
    with LOGIN_LOCK:
        if success:
            LOGIN_FAILURES.pop((ip, email), None)
        else:
            if len(LOGIN_FAILURES) >= 10000:
                now = time.monotonic()
                expired = [key for key, values in LOGIN_FAILURES.items() if not values or values[-1] < now - 60]
                for key in expired:
                    LOGIN_FAILURES.pop(key, None)
                if len(LOGIN_FAILURES) >= 10000:
                    LOGIN_FAILURES.pop(next(iter(LOGIN_FAILURES)))
            LOGIN_FAILURES.setdefault((ip, email), []).append(time.monotonic())


def hash_password(password: str) -> str:
    if len(password) < 10 or len(password) > 256:
        raise HTTPException(400, "Password must contain 10 to 256 characters")
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(digest, actual)
    except (ValueError, TypeError):
        return False


def public_user(user: User) -> dict:
    result = {key: getattr(user, key) for key in ("id", "name", "email", "role", "skills", "available", "active")}
    db = object_session(user)
    result["qualifications"] = sorted(row.qualification_id for row in db.query(UserQualification).filter_by(user_id=user.id, active=True).all()) if db else []
    return result


def create_session(db: Session, user: User, response: Response) -> dict:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    settings = get_settings()
    db.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                        csrf_token=csrf, expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=settings.session_hours * 3600,
                        httponly=True, samesite="lax", secure=settings.session_secure, path="/")
    return {"user": public_user(user), "csrf_token": csrf}


def session_for(request: Request, db: Session) -> LoginSession:
    token = request.cookies.get(COOKIE, "")
    session = db.get(LoginSession, hashlib.sha256(token.encode()).hexdigest()) if token else None
    if not session or session.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(401, "Sign in to continue")
    return session


def check_csrf(request: Request, session: LoginSession) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not hmac.compare_digest(request.headers.get("X-CSRF-Token", "").encode(), session.csrf_token.encode()):
            raise HTTPException(403, "Invalid CSRF token")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    session = session_for(request, db)
    check_csrf(request, session)
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Account is inactive")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return user


def require_operator(user: User = Depends(current_user)) -> User:
    if user.role != "operator":
        raise HTTPException(403, "Operator access required")
    return user
