import hmac

from fastapi import Header, HTTPException, status

from .config import settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Dependency: enforces X-API-Key when settings.api_key is set."""
    expected = settings.api_key
    if not expected:
        return
    # Constant-time comparison to avoid leaking the key via timing.
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
