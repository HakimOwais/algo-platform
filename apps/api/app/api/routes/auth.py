import base64
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.schemas.trading import LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest) -> LoginResponse:
    if payload.username != "admin" or payload.password != "admin":
        raise HTTPException(status_code=401, detail="Invalid credentials")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=8)
    token_raw = f"{payload.username}:{int(expires_at.timestamp())}"
    token = base64.urlsafe_b64encode(token_raw.encode("utf-8")).decode("utf-8")
    return LoginResponse(access_token=token)


@router.post("/logout")
async def logout() -> dict:
    return {"status": "ok"}

