
import uuid
import time
import pytest
import redis

from fastapi.testclient import TestClient

from app.main import app
from app.config import settings


@pytest.fixture
def token_client_id():
    client_id = f"pytest_token_{uuid.uuid4().hex}"

    yield client_id

    cleanup_client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
    )

    try:
        cleanup_client.delete(
            f"throttlr:token_bucket:{client_id}"
        )
    except redis.exceptions.RedisError:
        pass
    finally:
        cleanup_client.close()


def test_token_bucket_allows_five_and_blocks_sixth(
    token_client_id,
    monkeypatch,
):
    monkeypatch.setattr(settings, "token_bucket_capacity", 5)
    monkeypatch.setattr(settings, "token_bucket_refill_rate", 1)

    with TestClient(app) as client:

        for _ in range(5):
            response = client.get(
                f"/api/v1/ratelimit/token-bucket/{token_client_id}"
            )
            assert response.status_code == 200

        response = client.get(
            f"/api/v1/ratelimit/token-bucket/{token_client_id}"
        )

        assert response.status_code == 429
        assert response.json()["detail"] == "Too many requests"


def test_token_bucket_refills_after_time(
    token_client_id,
    monkeypatch,
):
    monkeypatch.setattr(settings, "token_bucket_capacity", 2)
    monkeypatch.setattr(settings, "token_bucket_refill_rate", 1)

    with TestClient(app) as client:

        # Consume both tokens.
        for _ in range(2):
            response = client.get(
                f"/api/v1/ratelimit/token-bucket/{token_client_id}"
            )
            assert response.status_code == 200

        # Bucket should now be empty.
        response = client.get(
            f"/api/v1/ratelimit/token-bucket/{token_client_id}"
        )
        assert response.status_code == 429

        # Wait for one token to refill.
        time.sleep(1.2)

        response = client.get(
            f"/api/v1/ratelimit/token-bucket/{token_client_id}"
        )

        assert response.status_code == 200
        assert response.json()["remaining_tokens"] == 0


def test_token_bucket_does_not_exceed_capacity(
    token_client_id,
    monkeypatch,
):
    monkeypatch.setattr(settings, "token_bucket_capacity", 5)
    monkeypatch.setattr(settings, "token_bucket_refill_rate", 1)

    with TestClient(app) as client:
        time.sleep(1)

        response = client.get(
            f"/api/v1/ratelimit/token-bucket/{token_client_id}"
        )

        assert response.status_code == 200
        assert response.json()["remaining_tokens"] <= 4


def test_token_bucket_redis_failure_returns_503(
    monkeypatch,
    token_client_id,
):
    async def mock_script(*args, **kwargs):
        raise redis.exceptions.ConnectionError(
            "Redis is unavailable"
        )

    monkeypatch.setattr(
        "app.main.token_bucket_script",
        mock_script,
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/ratelimit/token-bucket/{token_client_id}"
        )

        assert response.status_code == 503
        assert response.json()["detail"] == (
            "Rate-limiting service temporarily unavailable"
        )
