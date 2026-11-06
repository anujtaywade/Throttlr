
local key = KEYS[1]
local window_seconds = tonumber(ARGV[1])
local request_limit = tonumber(ARGV[2])

local count = redis.call("INCR", key)

if count == 1 then
    redis.call("EXPIRE", key, window_seconds)
end

local ttl = redis.call("TTL", key)

local allowed = 0
if count <= request_limit then
    allowed = 1 
end 

return {allowed, count, ttl}
