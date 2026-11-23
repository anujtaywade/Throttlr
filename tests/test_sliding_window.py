
import uuid
import pytest
import redis

from fastapi.testclient import TestClient

from app.main import app
from app.config import settings


@pytest.fixture
def sliding_client_id():
    client_id = f"pytest_sliding_{uuid.uuid4().hex}"

    yield client_id

    cleanup_client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    try:
        keys = cleanup_client.scan_iter(
            match=f"throttlr:sliding:{client_id}:*"
        )

        keys = list(keys)

        if keys:
            cleanup_client.delete(*keys)

    except redis.exceptions.RedisError:
        pass

    finally:
        cleanup_client.close()


def test_sliding_window_allows_five_requests_and_blocks_sixth(
    sliding_client_id,
    monkeypatch,
):
    # Use a long window to avoid crossing a window boundary during this test.
    monkeypatch.setattr(settings, "window_seconds", 3600)

    with TestClient(app) as client:

        for request_number in range(1, 6):
            response = client.get(
                f"/api/v1/ratelimit/sliding/{sliding_client_id}"
            )

            assert response.status_code == 200
            assert response.json()["current_requests"] == request_number
            assert response.json()["remaining"] == 5 - request_number

        response = client.get(
            f"/api/v1/ratelimit/sliding/{sliding_client_id}"
        )

        assert response.status_code == 429
        assert response.json()["detail"] == "Too many requests"
        assert response.headers["X-RateLimit-Limit"] == "5"
        assert response.headers["X-RateLimit-Remaining"] == "0"


def test_sliding_window_uses_previous_window_count(
    sliding_client_id,
    monkeypatch,
):
    window_seconds = 86400
    monkeypatch.setattr(settings, "window_seconds", window_seconds)

    redis_client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    try:
        redis_time = redis_client.time()[0]
        current_window = redis_time // window_seconds
        previous_window = current_window - 1

        previous_key = (
            f"throttlr:sliding:{sliding_client_id}:{previous_window}"
        )

        # Simulate four requests in the previous window.
        redis_client.set(previous_key, 4, ex=window_seconds * 2)

    finally:
        redis_client.close()

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/ratelimit/sliding/{sliding_client_id}"
        )

        assert response.status_code == 200

        data = response.json()

        assert data["previous_requests"] == 4
        assert data["current_requests"] == 1

        # The weighted estimate must include the previous window.
        assert 1 <= data["estimated_requests"] <= 5


def test_sliding_window_redis_failure_returns_503(
    monkeypatch,
    sliding_client_id,
):
    async def mock_script(*args, **kwargs):
        raise redis.exceptions.ConnectionError(
            "Redis is unavailable"
        )

    monkeypatch.setattr(
        "app.main.sliding_window_script",
        mock_script,
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/ratelimit/sliding/{sliding_client_id}"
        )

        assert response.status_code == 503
        assert response.json()["detail"] == (
            "Rate-limiting service temporarily unavailable"
        )
