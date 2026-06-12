"""Check DB status."""
from engine.store import Store
s = Store()
raw = s.conn.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0]
scored = s.conn.execute("SELECT COUNT(*) FROM scored_items WHERE domain='elderly-care'").fetchone()[0]
print(f"raw={raw}  scored={scored}")
s.close()
