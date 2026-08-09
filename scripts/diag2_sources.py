"""诊断2：待评分队列全量分布 + 信源精选转化率"""
import sys
sys.path.insert(0, ".")
from engine.store import Store

s = Store()

print("=== 待评分队列全量分布 (按采集时间) ===")
rows = s.conn.execute(
    "SELECT substr(r.fetched_at,1,10) d, COUNT(*) FROM raw_items r "
    "WHERE r.id NOT IN (SELECT raw_id FROM scored_items) "
    "GROUP BY d ORDER BY d DESC LIMIT 15"
).fetchall()
for d, c in rows:
    print(d, c)

print("\n=== 待评分队列最早50条按信源 ===")
rows = s.conn.execute(
    "SELECT r.source_id, COUNT(*) FROM raw_items r "
    "WHERE r.id NOT IN (SELECT raw_id FROM scored_items) "
    "GROUP BY r.source_id ORDER BY 2 DESC LIMIT 10"
).fetchall()
for src, c in rows:
    print(src, c)

print("\n=== 信源: 采集量 / 已评分 / 精选(>=6.0) / 精选率 ===")
rows = s.conn.execute(
    "SELECT r.source_id, "
    "  COUNT(*) total, "
    "  SUM(CASE WHEN s.id IS NOT NULL THEN 1 ELSE 0 END) scored, "
    "  SUM(CASE WHEN s.score>=6.0 THEN 1 ELSE 0 END) sel "
    "FROM raw_items r LEFT JOIN scored_items s ON s.raw_id=r.id AND s.domain='elderly-care' "
    "GROUP BY r.source_id HAVING total>=15 ORDER BY scored DESC LIMIT 14"
).fetchall()
print(f"{'source':<22} {'total':>6} {'scored':>6} {'sel':>5} {'sel%':>6}")
for src, total, scored, sel in rows:
    sel_pct = (sel / scored * 100) if scored else 0
    print(f"{src:<22} {total:>6} {scored:>6} {sel:>5} {sel_pct:>5.1f}%")

print("\n=== 评分分布 ===")
rows = s.conn.execute(
    "SELECT CASE WHEN score>=8.0 THEN '8.0+' WHEN score>=7.0 THEN '7.0-7.9' "
    "WHEN score>=6.0 THEN '6.0-6.9' WHEN score>=5.0 THEN '5.0-5.9' "
    "ELSE '<5.0' END bucket, COUNT(*) FROM scored_items WHERE domain='elderly-care' "
    "GROUP BY bucket ORDER BY bucket DESC"
).fetchall()
for b, c in rows:
    print(b, c)

s.close()
