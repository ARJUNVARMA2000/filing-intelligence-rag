from __future__ import annotations

from fastapi import Header, HTTPException, status
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token

from .dependencies import get_app_settings


def require_frontend_identity(authorization: str | None = Header(default=None)) -> None:
    """Restrict paid chat routes to the production frontend service account."""

    settings = get_app_settings()
    if settings.auth_mode == "disabled":
        if settings.app_env not in {"local", "development", "test"}:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Backend caller authentication is not safely configured.",
            )
        return

    expected_email = settings.frontend_service_account
    expected_audience = settings.backend_audience
    if not expected_email or not expected_audience:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backend caller authentication is not fully configured.",
        )

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A Google-signed frontend identity token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = id_token.verify_oauth2_token(
            token,
            GoogleAuthRequest(),
            audience=expected_audience,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The frontend identity token is invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if claims.get("email") != expected_email or claims.get("email_verified") is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The caller is not authorized to use paid chat routes.",
        )
