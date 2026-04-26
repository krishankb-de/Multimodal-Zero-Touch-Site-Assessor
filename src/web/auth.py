"""FastAPI dependency for installer API-key authentication.

Usage:
    @router.post("/some-route")
    async def handler(installer_id: str = Depends(require_installer_auth)):
        ...

Configure valid keys via the INSTALLER_API_KEYS env var (comma-separated).
Each request must supply:  Authorization: Bearer <api-key>
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.common.config import config

_bearer_scheme = HTTPBearer(auto_error=False)


def require_installer_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """
    Validate a Bearer token against the configured installer API keys.

    Returns the token (usable as an installer identifier) on success.
    Raises 401 when the Authorization header is missing or malformed.
    Raises 403 when the token is present but not in the allowed-key set.
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required — supply 'Authorization: Bearer <api-key>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # When no keys are configured (dev/test) every non-empty token is accepted
    # so tests don't need to inject a real key.  Production must set INSTALLER_API_KEYS.
    if config.auth.api_keys and token not in config.auth.api_keys:
        raise HTTPException(
            status_code=403,
            detail="Invalid installer API key",
        )

    return token
