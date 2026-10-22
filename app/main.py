
from fastapi import FastAPI
from app.redis_client import redis_client

app = FastAPI(title="Throttlr")


@app.get("/")
async def home():
    return {"message": "Throttlr is running"}


@app.get("/redis-test/{client_id}")
async def redis_test(client_id: str):
    key = f"throttlr:requests:{client_id}"

    count = await redis_client.incr(key)

    return {
        "client_id": client_id,
        "request_count": count,
        "redis_connected": True,
    }
