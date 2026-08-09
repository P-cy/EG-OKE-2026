-- vote.lua — บันทึกโหวตแบบ atomic ใน round-trip เดียว
--
-- ทำไมต้องเป็น Lua: การ dedupe + นับคะแนน + เข้าคิว ต้องเกิดพร้อมกันหรือไม่เกิดเลย
-- ถ้าแยกเป็นหลายคำสั่ง จะมี race condition ตอน 2,000 คนกดพร้อมกัน
-- และ Lua ทำให้ทั้งหมดเป็น 1 network round-trip → นี่คือเหตุผลที่รับได้ >20k rps
--
-- KEYS[1] = dedupe key   vote:{round}:{uid}
-- KEYS[2] = tally hash   tally:{round}
-- KEYS[3] = zset         lb:vote:{round}
-- KEYS[4] = stream       stream:votes
--
-- ARGV[1] = user_id
-- ARGV[2] = artist_id
-- ARGV[3] = round_key
-- ARGV[4] = dedupe TTL (วินาที)
-- ARGV[5] = timestamp (ms)
-- ARGV[6] = ip_hash
-- ARGV[7] = maxlen ของ stream (approx trim)
--
-- return: { accepted(1/0), artist_id, total_for_artist }

local existing = redis.call('GET', KEYS[1])
if existing then
  -- โหวตไปแล้ว → คืนของเดิม ไม่ error (idempotent)
  -- ผู้ใช้กดซ้ำเพราะเน็ตช้าเป็นเรื่องปกติมาก ห้ามตอบ error
  local cur = redis.call('HGET', KEYS[2], existing)
  return { 0, existing, tonumber(cur) or 0 }
end

redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[4]))
local total = redis.call('HINCRBY', KEYS[2], ARGV[2], 1)
redis.call('ZINCRBY', KEYS[3], 1, ARGV[2])
redis.call('XADD', KEYS[4], 'MAXLEN', '~', tonumber(ARGV[7]), '*',
           'u', ARGV[1],
           'a', ARGV[2],
           'r', ARGV[3],
           't', ARGV[5],
           'ip', ARGV[6])

return { 1, ARGV[2], total }
