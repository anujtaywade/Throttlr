
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError


class RateLimitMiddleware:
    def __init__(
        self,
        app,
        redis_client,
        rate_limit_script,
        limit: int = 5,
        window_seconds: int = 60,
    ):
        self.app = app
        self.redis_client = redis_client
        self.rate_limit_script = rate_limit_script
        self.limit = limit
        self.window_seconds = window_seconds

    async def __call__(self, scope, receive, send):

        # Allow non-HTTP traffic to pass through.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        # Exclude existing algorithm testing endpoints.
        if path.startswith("/api/v1/ratelimit/"):
            await self.app(scope, receive, send)
            return

        # Identify the client using its IP address.
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"

        key = f"throttlr:middleware:fixed:{client_ip}"

        try:
            result = await self.rate_limit_script(
                keys=[key],
                args=[self.window_seconds, self.limit],
            )

        except RedisError:
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": "Rate-limiting service temporarily unavailable"
                },
            )
            await response(scope, receive, send)
            return

        allowed, count, ttl = result

        remaining = max(self.limit - count, 0)

        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(max(ttl, 0)),
        }

        # Reject requests that exceed the limit.
        if allowed == 0:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={
                    **headers,
                    "Retry-After": str(max(ttl, 0)),
                },
            )
            await response(scope, receive, send)
            return

        # Convert rate-limit headers into ASGI byte format.
        header_bytes = {
            name.lower().encode("latin-1"): value.encode("latin-1")
            for name, value in headers.items()
        }

        # Intercept the response before sending it to the client.
        async def send_with_rate_limit_headers(message):

            if message["type"] == "http.response.start":

                existing_headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in header_bytes
                ]

                message = {
                    **message,
                    "headers": existing_headers + list(header_bytes.items()),
                }

            await send(message)

        # Pass the wrapped send function to the application.
        await self.app(scope, receive, send_with_rate_limit_headers)
