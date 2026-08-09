"""诊断：近8天评分产出 + 待评分队列按采集时间分布"""
import sys
sys.path.insert(0, ".")
from engine.store import Store

s = Store()

print("=== 近8天评分产出 (scored_items) ===")
rows = s.conn.execute(
    "SELECT substr(created_at,1,10) d, COUNT(*) FROM scored_items "
    "WHERE domain=? AND created_at>=datetime('now','-8 days') "
    "GROUP BY d ORDER BY d DESC", ("elderly-care",)
).fetchall()
for d, c in rows:
    print(d, c)

print("\n=== 待评分队列按采集时间分布 ===")
rows = s.conn.execute(
    "SELECT substr(r.created_at,1,10) d, COUNT(*) FROM raw_items r "
    "WHERE r.id NOT IN (SELECT raw_id FROM scored_items) "
    "GROUP BY d ORDER BY d DESC LIMIT 10"
).fetchall()
for d, c in rows:
    print(d, c)

print("\n=== 每日精选(>=6.0)产出 ===")
rows = s.conn.execute(
    "SELECT substr(created_at,1,10) d, COUNT(*) FROM scored_items "
    "WHERE domain=? AND score>=6.0 AND created_at>=datetime('now','-8 days') "
    "GROUP BY d ORDER BY d DESC", ("elderly-care",)
).fetchall()
for d, c in rows:
    print(d, c)

s.close()
