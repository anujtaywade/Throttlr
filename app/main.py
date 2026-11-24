from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse 
from app.redis_client import redis_client
from app.config import settings
from contextlib import asynccontextmanager
from redis.exceptions import RedisError
from app.middleware.rate_limit import RateLimitMiddleware
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

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



sliding_script_path = Path(__file__).parent / "scripts" / "sliding_window.lua"
sliding_script_source = sliding_script_path.read_text()

sliding_window_script = redis_client.register_script(sliding_script_source)



token_bucket_path = Path(__file__).parent / "scripts" / "token_bucket.lua"
token_bucket_source = token_bucket_path.read_text()
token_bucket_script = redis_client.register_script(token_bucket_source)

app.add_middleware(
    RateLimitMiddleware,
    redis_client=redis_client,
    rate_limit_script=fixed_window_script,
    limit=settings.req_limit,
    window_seconds=settings.window_seconds,
)

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



@app.get("/api/v1/ratelimit/sliding/{client_id}")
async def check_sliding_rate_limit(client_id: str):
    try:
        result = await sliding_window_script(
            keys=[],
            args=[
                client_id,
                settings.window_seconds,
                settings.req_limit,
            ],
        )

    except RedisError as exc:
        raise HTTPException(
            status_code=503,
            detail="Rate-limiting service temporarily unavailable",
        ) from exc

    allowed, current_count, previous_count, estimated_count = result

    remaining = max(
        int(settings.req_limit - estimated_count - 1),
        0,
    )

    rate_limit_headers = {
        "X-RateLimit-Limit": str(settings.req_limit),
        "X-RateLimit-Remaining": str(remaining),
    }

    if allowed == 0:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers=rate_limit_headers,
        )

    return JSONResponse(
        content={
            "client_id": client_id,
            "algorithm": "sliding_window",
            "current_requests": current_count,
            "previous_requests": previous_count,
            "estimated_requests": round(estimated_count + 1, 2),
            "limit": settings.req_limit,
            "remaining": remaining,
        },
        headers=rate_limit_headers,
    )



@app.get("/api/v1/ratelimit/token-bucket/{client_id}")
async def check_token_bucket(client_id: str):
    key = f"throttlr:token_bucket:{client_id}"

    try:
        result = await token_bucket_script(
            keys=[key],
            args=[
                settings.token_bucket_capacity,
                settings.token_bucket_refill_rate,
            ],
        )

    except RedisError as exc:
        raise HTTPException(
            status_code=503,
            detail="Rate-limiting service temporarily unavailable",
        ) from exc

    allowed, remaining_tokens, elapsed = result

    remaining_tokens = float(remaining_tokens)

    rate_limit_headers = {
        "X-RateLimit-Limit": str(settings.token_bucket_capacity),
        "X-RateLimit-Remaining": str(int(remaining_tokens)),
    }

    if allowed == 0:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers=rate_limit_headers,
        )

    return JSONResponse(
        content={
            "client_id": client_id,
            "algorithm": "token_bucket",
            "allowed": True,
            "capacity": settings.token_bucket_capacity,
            "remaining_tokens": remaining_tokens,
            "refill_rate_per_second": settings.token_bucket_refill_rate,
            "elapsed_seconds": elapsed,
        },
        headers=rate_limit_headers,
    )



@app.get("/api/v1/protected")
async def protected_route():
    return {
        "message": "You have accessed a protected route!",
        "status": "success",
    }


@app.get("/metrics")
async def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )