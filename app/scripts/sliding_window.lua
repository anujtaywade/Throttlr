local client_id = ARGV[1]
local window_seconds = tonumber(ARGV[2])
local request_limit = tonumber(ARGV[3])

-- Get current Redis server time
local time = redis.call("TIME")
local current_time = tonumber(time[1])

-- Identify the current window
local current_window = math.floor(current_time / window_seconds)
local previous_window = current_window - 1

-- Create Redis keys
local previous_key = "throttlr:sliding:" .. client_id .. ":" .. previous_window
local current_key = "throttlr:sliding:" .. client_id .. ":" .. current_window

-- Get request counts
local previous_count = tonumber(redis.call("GET", previous_key) or 0)
local current_count = tonumber(redis.call("GET", current_key) or 0)

-- Calculate elapsed fraction
local elapsed = (current_time % window_seconds) / window_seconds

-- Calculate weighted request count
local estimated_count =
    previous_count * (1 - elapsed) + current_count

local projected_count = estimated_count + 1

-- Check request limit
local allowed = 0

if projected_count  <= request_limit then
    allowed = 1
    current_count = redis.call("INCR", current_key)
end

-- Set expiration
redis.call("EXPIRE", current_key, window_seconds * 2)

return {
    allowed,
    current_count,
    previous_count,
    estimated_count
}