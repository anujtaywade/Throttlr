from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse 
from app.redis_client import redis_client

app = FastAPI(title="Throttlr")

REQ_LIMIT = 5
WINDOW_SECONDS = 60 

script_path = Path(__file__).parent / "scripts" / "fixed_window.lua"
script_source = script_path.read_text()

fixed_window_script = redis_client.register_script(script_source)


@app.get("/")
async def home():
    return {"message": "Throttlr is running"}


@app.get("/api/v1/ratelimit/check/{client_id}")
async def check_rate_limit(client_id: str):
    key = f"throttlr:requests:{client_id}"

    # Execute Lua script
    result = await fixed_window_script(
        keys=[key],
        args=[WINDOW_SECONDS,REQ_LIMIT],
    )

    # Get counter and TTL from Lua
    allowed, count, ttl = result

    remaining = max(REQ_LIMIT - count, 0)

    # Check request limit
    if allowed == 0 :
        retry_after = max(ttl, 0)

        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after)},
        )

    return JSONResponse(
        content={
        "client_id": client_id,
        "requests_used": count,
        "allowed": True,
        "limit": REQ_LIMIT,
        "remaining": remaining,
        "window_expire_in_seconds": max(ttl, 0),
    }
    )