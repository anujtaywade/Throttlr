
import asyncio
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.main import app
from app.middleware.rate_limit import RateLimitMiddleware


def test_middleware_allows_five_requests_and_blocks_sixth():
    with TestClient(app) as client:
        for i in range(5):
            response = client.get("/api/v1/protected")

            assert response.status_code == 200
            assert response.headers["X-RateLimit-Limit"] == "5"
            assert int(response.headers["X-RateLimit-Remaining"]) == 4 - i

        response = client.get("/api/v1/protected")

        assert response.status_code == 429
        assert response.json()["detail"] == "Too many requests"
        assert response.headers["X-RateLimit-Remaining"] == "0"
        assert "Retry-After" in response.headers


def test_middleware_returns_503_when_redis_fails():

    mock_script = AsyncMock(
        side_effect=RedisError("Redis unavailable")
    )

    async def fake_app(scope, receive, send):
        pass

    middleware = RateLimitMiddleware(
        app=fake_app,
        redis_client=None,
        rate_limit_script=mock_script,
        limit=5,
        window_seconds=60,
    )

    sent_messages = []

    async def receive():
        return {
            "type": "http.request",
            "body": b"",
            "more_body": False,
        }

    async def send(message):
        sent_messages.append(message)

    scope = {
        "type": "http",
        "path": "/api/v1/protected",
        "method": "GET",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }

    asyncio.run(middleware(scope, receive, send))

    response_start = next(
        message
        for message in sent_messages
        if message["type"] == "http.response.start"
    )

    assert response_start["status"] == 503
