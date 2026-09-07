from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    access_token: str


@lru_cache
def _jwk_client(url: str) -> PyJWKClient:
    return PyJWKClient(
        f"{url.rstrip('/')}/auth/v1/.well-known/jwks.json",
        cache_keys=True,
        lifespan=300,
    )


def _verify_remotely(token: str) -> CurrentUser:
    settings = get_settings()
    try:
        response = httpx.get(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
            headers={
                "apikey": settings.supabase_publishable_key,
                "Authorization": f"Bearer {token}",
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return CurrentUser(
            id=str(payload["id"]),
            email=payload.get("email"),
            access_token=token,
        )
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc


def verify_access_token(token: str) -> CurrentUser:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    try:
        header = jwt.get_unverified_header(token)
        algorithm = str(header.get("alg", ""))
        if algorithm not in {"RS256", "ES256"}:
            return _verify_remotely(token)
        signing_key = _jwk_client(settings.supabase_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[algorithm],
            audience="authenticated",
            issuer=f"{settings.supabase_url.rstrip('/')}/auth/v1",
        )
        return CurrentUser(
            id=str(claims["sub"]),
            email=claims.get("email"),
            access_token=token,
        )
    except HTTPException:
        raise
    except (jwt.PyJWTError, KeyError, ValueError):
        return _verify_remotely(token)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Sign in required")
    return verify_access_token(credentials.credentials)
