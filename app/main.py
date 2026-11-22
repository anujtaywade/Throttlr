from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse 
from app.redis_client import redis_client
from app.config import settings
from contextlib import asynccontextmanager
from redis.exceptions import RedisError

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Application startup
    await redis_client.ping()
    print("Redis connection established")

    try:
        yield
    finally:
        # Application shutdown
        await redis_client.aclose()
        print("Redis connection closed")


app = FastAPI(title="Throttlr", lifespan=lifespan)



script_path = Path(__file__).parent / "scripts" / "fixed_window.lua"
script_source = script_path.read_text()

fixed_window_script = redis_client.register_script(script_source)


@app.get("/")
async def home():
    return {"message": "Throttlr is running"}


@app.get("/api/v1/ratelimit/check/{client_id}")
async def check_rate_limit(client_id: str):
    key = f"throttlr:requests:{client_id}"

    try:
        result = await fixed_window_script(
            keys=[key],
            args=[settings.window_seconds, settings.req_limit],
        )

    except RedisError as exc:
        raise HTTPException(
            status_code=503,
            detail="Rate-limiting service temporarily unavailable",
        ) from exc

    # Get counter and TTL from Lua
    allowed, count, ttl = result

    remaining = max(settings.req_limit - count, 0)
    reset_time = max(ttl, 0)

    # Common rate-limit headers
    rate_limit_headers = {
        "X-RateLimit-Limit": str(settings.req_limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_time),
    }

    # Check request limit
    if allowed == 0:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={
                **rate_limit_headers,
                "Retry-After": str(reset_time),
            },
        )

    return JSONResponse(
        content={
            "client_id": client_id,
            "requests_used": count,
            "allowed": True,
            "limit": settings.req_limit,
            "remaining": remaining,
            "window_expire_in_seconds": reset_time,
        },
        headers=rate_limit_headers,
    )
