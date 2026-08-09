"""查公众号源在 raw_items 中的最新采集情况"""
import sys
sys.path.insert(0, ".")
from engine.store import Store

s = Store()
for src in ["wx_changhuxqgc", "wx_zgylbx", "wx_zglnjy", "wx_guojiaminzheng", "wx_agetech"]:
    rows = s.conn.execute(
        "SELECT COUNT(*) total, MAX(fetched_at) last_fetch, MIN(fetched_at) first_fetch "
        "FROM raw_items WHERE source_id=?", (src,)
    ).fetchone()
    print(f"{src:<18} total={rows['total']:>4} first={str(rows['first_fetch'])[:10]} last={str(rows['last_fetch'])[:19]}")

print("\n=== 最近3天有哪些源在采集 ===")
rows = s.conn.execute(
    "SELECT source_id, COUNT(*) c FROM raw_items WHERE fetched_at>=datetime('now','-3 days') "
    "GROUP BY source_id ORDER BY c DESC"
).fetchall()
for r in rows:
    print(f"{r['source_id']:<22} {r['c']}")
s.close()
