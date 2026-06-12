"""Generate dashboard HTML for elderly-care domain."""
import json
from engine.store import Store
from pathlib import Path
from datetime import datetime

s = Store()
items = s.get_selected('elderly-care', take=500, min_score=0)
stats = s.get_stats('elderly-care')
s.close()

selected = [i for i in items if i.get('score', 0) >= 6.0]

CAT = {
    'policy': '政策法规', 'industry': '行业动态', 'health_services': '健康服务',
    'elderly_tech': '智慧养老', 'finance_security': '养老金融', 'lifestyle': '养老生活',
    'risk': '风险预警', 'case_study': '案例与观点',
}

def esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

cards = []
for it in items:
    sc = it.get('score', 0)
    cls = 'hot' if sc >= 8 else 'warm'
    title = esc(it.get('title_display') or it.get('title', ''))
    url = it.get('url', '#')
    cat = CAT.get(it.get('category', ''), it.get('category', ''))
    src = esc(it.get('source_display') or it.get('source_id', ''))
    summary = esc(it.get('summary', ''))
    reason = esc(it.get('reason', ''))
    pts = it.get('key_points', []) or []
    tags = it.get('tags', []) or []
    ents = it.get('entities', []) or []
    pub = (it.get('published', '') or '')[:10]

    pts_html = ''
    if pts:
        pts_html = '<ul class="points">' + ''.join(f'<li>{esc(p)}</li>' for p in pts) + '</ul>'

    tags_html = ''
    if ents or tags:
        tags_html = '<div class="tags">' + ''.join(f'<span class="entity">📌 {esc(e)}</span>' for e in ents) + ''.join(f'<span class="tag">#{esc(t)}</span>' for t in tags) + '</div>'

    summary_html = f'<p class="summary">{summary}</p>' if summary else ''
    reason_html = f'<p class="reason">💡 {reason}</p>' if reason else ''

    cards.append(f'''<div class="card">
  <div class="card-header">
    <div class="score {cls}">{sc:.1f}</div>
    <div class="card-body">
      <div class="card-title"><a href="{url}" target="_blank">{title}</a></div>
      <div class="card-meta">
        <span class="pill pill-cat">{cat}</span>
        <span class="pill pill-src">{src}</span>
        <span class="pill pill-src">{pub}</span>
      </div>
      {summary_html}
      {pts_html}
      {reason_html}
      {tags_html}
    </div>
  </div>
</div>''')

date_str = stats.get('date', datetime.now().strftime('%Y-%m-%d'))

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>银发产业情报</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;background:#f5f5f4;color:#1c1917;padding:20px;max-width:900px;margin:0 auto}}
.header{{text-align:center;margin-bottom:24px}}
.header h1{{font-size:24px;font-weight:700}}
.header p{{color:#78716c;font-size:14px;margin-top:4px}}
.stats{{display:flex;gap:16px;justify-content:center;margin-bottom:24px;flex-wrap:wrap}}
.stat{{background:#fff;padding:12px 20px;border-radius:8px;text-align:center;min-width:100px}}
.stat .num{{font-size:24px;font-weight:700;color:#a16207}}
.stat .label{{font-size:12px;color:#78716c;margin-top:2px}}
.cards{{display:flex;flex-direction:column;gap:8px}}
.card{{background:#fff;border-radius:8px;padding:16px;border:1px solid #e7e5e4}}
.card-header{{display:flex;gap:12px}}
.score{{min-width:40px;height:28px;display:flex;align-items:center;justify-content:center;border-radius:6px;font-weight:700;font-size:14px;color:#fff;flex-shrink:0}}
.score.hot{{background:#dc2626}}
.score.warm{{background:#f59e0b}}
.card-body{{flex:1;min-width:0}}
.card-title{{font-size:15px;font-weight:600;line-height:1.4;margin-bottom:6px}}
.card-title a{{color:#1c1917;text-decoration:none}}
.card-title a:hover{{color:#a16207}}
.card-meta{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}}
.pill{{padding:1px 8px;border-radius:999px;font-size:11px;font-weight:500}}
.pill-cat{{background:#fef9c3;color:#a16207}}
.pill-src{{background:#f5f5f4;color:#78716c}}
.summary{{font-size:13px;color:#57534e;line-height:1.6;margin-bottom:6px}}
.points{{margin:6px 0 6px 16px;font-size:12px;color:#57534e;line-height:1.6}}
.reason{{font-size:12px;color:#78716c;margin-top:4px;font-style:italic}}
.tags{{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}}
.tag{{font-size:11px;background:#f5f5f4;color:#78716c;padding:1px 6px;border-radius:4px}}
.entity{{font-size:11px;background:#fefce8;color:#a16207;padding:1px 6px;border-radius:4px}}
</style>
</head>
<body>
<div class="header">
  <h1>🏦 银发产业情报</h1>
  <p>{date_str} · Intel Pipeline · {len(selected)} 条精选</p>
</div>
<div class="stats">
  <div class="stat"><div class="num">{stats.get("total_fetched", 0)}</div><div class="label">采集</div></div>
  <div class="stat"><div class="num">{len(items)}</div><div class="label">评分</div></div>
  <div class="stat"><div class="num">{len(selected)}</div><div class="label">精选</div></div>
</div>
<div class="cards">
{"".join(cards)}
</div>
</body>
</html>'''

Path('data/dashboard-elderly-care.html').write_text(html, encoding='utf-8')
print(f'Dashboard: {len(items)} items, {len(selected)} selected')
