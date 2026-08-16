"""Authentication router — admin login endpoint."""

import hashlib
import base64
import logging
import os
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.orm import Session

from db.session import get_db
from models.models import AdminUser

logger = logging.getLogger(__name__)

from jose import jwt
from pydantic import BaseModel

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _prepare_password(password: str) -> bytes:
    """SHA-256 + base64 pre-hash so any length password fits in 72 bytes."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare_password(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prepare_password(plain), hashed.encode("utf-8"))


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse)
def login(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Verify admin credentials and issue a signed JWT valid for 8 hours.

    Accepts application/x-www-form-urlencoded with fields ``username`` (email)
    and ``password`` — matching the OAuth2 password flow convention used by
    the frontend.
    """
    try:
        user = db.query(AdminUser).filter(AdminUser.email == username).first()
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
        payload = {
            "sub": str(user.id),
            "email": user.email,
            "is_admin": True,
            "exp": expire,
        }
        token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
        return TokenResponse(access_token=token, token_type="bearer")
    except HTTPException:
        raise
    except Exception:
        logger.exception("login failed")
        raise HTTPException(status_code=500, detail="Internal server error")
