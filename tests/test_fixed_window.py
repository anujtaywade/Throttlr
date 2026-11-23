import uuid
import pytest
import redis
import time

from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.redis_client import redis_client


@pytest.fixture
def test_client_id():
    client_id = f"pytest_{uuid.uuid4().hex}"

    yield client_id

    # Cleanup after test
    cleanup_client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    try:
        cleanup_client.delete(f"throttlr:requests:{client_id}")
    except redis.exceptions.RedisError:
        pass
    finally:
        cleanup_client.close()


def test_fixed_window_allows_five_requests_and_blocks_sixth(test_client_id):
    with TestClient(app) as client:

        for request_number in range(1, 6):
            response = client.get(
                f"/api/v1/ratelimit/check/{test_client_id}"
            )

            assert response.status_code == 200
            assert response.json()["requests_used"] == request_number
            assert response.json()["remaining"] == 5 - request_number

        response = client.get(
            f"/api/v1/ratelimit/check/{test_client_id}"
        )

        assert response.status_code == 429
        assert response.json()["detail"] == "Too many requests"
        assert response.headers["X-RateLimit-Limit"] == "5"
        assert response.headers["X-RateLimit-Remaining"] == "0"
        assert "Retry-After" in response.headers

def test_fixed_window_resets_after_expiration(test_client_id, monkeypatch):
    # Temporarily set window duration to 2 seconds
    monkeypatch.setattr(settings, "window_seconds", 2)

    with TestClient(app) as client:

        # First 5 requests should be allowed
        for _ in range(5):
            response = client.get(
                f"/api/v1/ratelimit/check/{test_client_id}"
            )
            assert response.status_code == 200

        # Sixth request should be blocked
        response = client.get(
            f"/api/v1/ratelimit/check/{test_client_id}"
        )
        assert response.status_code == 429

        # Wait for the Redis key to expire
        time.sleep(2.1)

        # A new window should start
        response = client.get(
            f"/api/v1/ratelimit/check/{test_client_id}"
        )

        assert response.status_code == 200
        assert response.json()["requests_used"] == 1
        assert response.json()["remaining"] == 4

def test_redis_script_failure_returns_503(monkeypatch, test_client_id):
    async def mock_script(*args, **kwargs):
        raise redis.exceptions.ConnectionError("Redis is unavailable")

    monkeypatch.setattr("app.main.fixed_window_script", mock_script)

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/ratelimit/check/{test_client_id}"
        )

        assert response.status_code == 503
        assert response.json()["detail"] == (
            "Rate-limiting service temporarily unavailable"
        )

def test_rate_limit_headers(test_client_id):
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/ratelimit/check/{test_client_id}"
        )

        assert response.status_code == 200

        assert response.headers["X-RateLimit-Limit"] == "5"
        assert response.headers["X-RateLimit-Remaining"] == "4"
        assert "X-RateLimit-Reset" in response.headers