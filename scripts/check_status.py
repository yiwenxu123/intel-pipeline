"""Check database status."""
from engine.store import Store
s = Store()
raw = s.conn.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0]
scored = s.conn.execute("SELECT COUNT(*) FROM scored_items WHERE domain='elderly-care'").fetchone()[0]
selected = s.conn.execute("SELECT COUNT(*) FROM scored_items WHERE domain='elderly-care' AND score>=6.0").fetchone()[0]
print(f"原始: {raw}")
print(f"已评分: {scored}")
print(f"精选: {selected}")

# Also show some scored items
rows = s.conn.execute("""
    SELECT s.score, s.title_display, s.source_display
    FROM scored_items s
    WHERE s.domain='elderly-care' AND s.score>=6.0
    ORDER BY s.score DESC LIMIT 5
""").fetchall()
print("\n精选条目:")
for r in rows:
    print(f"  [{r['score']:.1f}] {r['title_display'][:40]} | {r['source_display']}")
s.close()
