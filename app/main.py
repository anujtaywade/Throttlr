
from fastapi import FastAPI, HTTPException
from app.redis_client import redis_client

app = FastAPI(title="Throttlr")

REQ_LIMIT = 5
WINDOW_SECONDS = 60 


@app.get("/")
async def home():
    return {"message": "Throttlr is running"}


@app.get("/api/v1/ratelimit/check/{client_id}")
async def check_rate_limit(client_id: str):
    key = f"throttlr:requests:{client_id}"

    count = await redis_client.incr(key)

    if count == 1 :
        await redis_client.expire(key,WINDOW_SECONDS)

    if count > REQ_LIMIT :
        ttl = await redis_client.ttl(key)
        retry_after = max(ttl,0)

        raise HTTPException(
            status_code = 429,
            detail = "Too many requests",
            headers ={ "retry-after" : str(retry_after)}
        )

    ttl = await redis_client.ttl(key)

    return {
        "client_id": client_id,
        "requests_used": count,
        "allowed": True,
        "limit" : REQ_LIMIT,
        "remaining" : REQ_LIMIT - count ,
        "window_expire_in_seconds" : max(ttl,0)
    }
