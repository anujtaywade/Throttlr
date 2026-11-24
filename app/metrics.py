
from prometheus_client import Counter, Histogram


# Total number of HTTP requests processed.
REQUEST_COUNT = Counter(
    "throttlr_requests_total",
    "Total number of HTTP requests processed",
    ["method", "status"],
)


# Total number of requests rejected by the rate limiter.
REJECTED_REQUEST_COUNT = Counter(
    "throttlr_rejected_requests_total",
    "Total number of requests rejected by the rate limiter",
)


# Time taken to process HTTP requests.
REQUEST_LATENCY = Histogram(
    "throttlr_request_latency_seconds",
    "HTTP request processing latency in seconds",
    ["method"],
)
