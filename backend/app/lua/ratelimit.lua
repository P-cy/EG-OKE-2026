-- ratelimit.lua — sliding window counter
--
-- ทำไมไม่ใช้ fixed window: fixed window ปล่อยให้ยิงได้ 2 เท่าที่ขอบหน้าต่าง
--   (เช่น 30 req ตอน 0:59 + 30 req ตอน 1:01 = 60 req ใน 2 วินาที)
-- ทำไมไม่ใช้ sliding log: เก็บทุก timestamp เปลือง memory มากตอนมี 5,000 user
-- sliding window counter = ประมาณค่าจาก 2 หน้าต่าง แม่นพอและถูกมาก
--
-- KEYS[1] = current bucket   rl:{scope}:{id}:{window_index}
-- KEYS[2] = previous bucket  rl:{scope}:{id}:{window_index-1}
--
-- ARGV[1] = limit
-- ARGV[2] = window (วินาที)
-- ARGV[3] = elapsed ratio ในหน้าต่างปัจจุบัน (0.0-1.0)
--
-- return: { allowed(1/0), remaining, retry_after }

local limit   = tonumber(ARGV[1])
local window  = tonumber(ARGV[2])
local elapsed = tonumber(ARGV[3])

local cur  = tonumber(redis.call('GET', KEYS[1])) or 0
local prev = tonumber(redis.call('GET', KEYS[2])) or 0

-- ถ่วงน้ำหนักหน้าต่างก่อนหน้าตามสัดส่วนที่ยังเหลือ
local estimated = prev * (1 - elapsed) + cur

if estimated >= limit then
  local retry = math.ceil(window * (1 - elapsed))
  if retry < 1 then retry = 1 end
  return { 0, 0, retry }
end

local newcur = redis.call('INCR', KEYS[1])
if newcur == 1 then
  redis.call('EXPIRE', KEYS[1], window * 2)
end

local remaining = math.floor(limit - estimated - 1)
if remaining < 0 then remaining = 0 end
return { 1, remaining, 0 }
