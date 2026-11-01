
local key = KEYS[1]
local window_seconds = tonumber(ARGV[1])

local count = redis.call("INCR", key)

if count == 1 then
    redis.call("EXPIRE", key, window_seconds)
end

local ttl = redis.call("TTL", key)

return {count, ttl}
