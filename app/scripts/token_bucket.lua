
local key = KEYS[1]

local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])

-- Get current Redis server time
local time = redis.call("TIME")
local current_time =
    tonumber(time[1]) + tonumber(time[2]) / 1000000

-- Read existing bucket state
local bucket = redis.call("HMGET", key, "tokens", "last_refill")

local tokens = tonumber(bucket[1]) or capacity
local last_refill = tonumber(bucket[2]) or current_time

-- Calculate elapsed time
local elapsed = math.max(current_time - last_refill, 0)

-- Refill tokens
local refilled_tokens = elapsed * refill_rate

tokens = math.min(capacity, tokens + refilled_tokens)

-- Check whether a token is available
local allowed = 0

if tokens >= 1 then
    allowed = 1
    tokens = tokens - 1
end

-- Save updated bucket state
redis.call(
    "HSET",
    key,
    "tokens", tokens,
    "last_refill", current_time
)

-- Keep the bucket key from staying forever
redis.call("EXPIRE", key, math.ceil(capacity / refill_rate) + 60)

return {
    allowed,
    tokens,
    elapsed
}
