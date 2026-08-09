"""查看指定信源在 source_metrics 中的详细记录"""
import sys
sys.path.insert(0, ".")
from engine.store import Store

s = Store()

for src in ["weibo_hot", "baidu_hot", "zhihu_hot", "wx_zgylbx", "wx_zglnjy", "wx_changhuxqgc", "joint_kaigo"]:
    rows = s.conn.execute(
        "SELECT source_id, COUNT(*) days, SUM(fetched) fetched, SUM(selected) selected, "
        "AVG(yield_rate) avg_yield, MIN(date) first_d, MAX(date) last_d "
        "FROM source_metrics WHERE domain='elderly-care' AND source_id=? GROUP BY source_id",
        (src,),
    ).fetchall()
    for r in rows:
        print(f"{r['source_id']:<18} days={r['days']:>3} fetched={r['fetched']:>4} "
              f"selected={r['selected']:>3} avg_yield={r['avg_yield']*100:5.1f}% "
              f"range={r['first_d']} ~ {r['last_d']}")

print("\n=== weibo_hot 每日明细 ===")
rows = s.conn.execute(
    "SELECT date, fetched, selected, yield_rate FROM source_metrics "
    "WHERE domain='elderly-care' AND source_id='weibo_hot' ORDER BY date DESC LIMIT 10"
).fetchall()
for r in rows:
    print(r["date"], "fetched=", r["fetched"], "selected=", r["selected"], f"yield={r['yield_rate']*100:.0f}%")

s.close()
