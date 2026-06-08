"""REST API 服务：对外暴露情报查询接口，同时托管前端页面。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from engine.config import settings
from engine.store import Store

app = FastAPI(
    title="Intel Pipeline API",
    description="可配置的行业情报引擎",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

store: Store | None = None
_domain_source_map: dict[str, dict[str, str]] = {}


def get_store() -> Store:
    global store
    if store is None:
        store = Store()
    return store


def _get_source_map(domain: str) -> dict[str, str]:
    """获取信源 ID → 名称映射（带缓存）。"""
    if domain not in _domain_source_map:
        try:
            from engine.domain import load_domain
            dc = load_domain(domain)
            _domain_source_map[domain] = {s.id: s.name for s in dc.sources}
        except Exception:
            _domain_source_map[domain] = {}
    return _domain_source_map[domain]


# ── API 路由 ──

@app.get("/api/items")
def get_items(
    domain: str = Query(default="elderly-care"),
    mode: str = Query(default="selected", description="selected / all"),
    category: Optional[str] = None,
    source_id: Optional[str] = None,
    since: Optional[str] = None,
    days: Optional[int] = Query(default=None, description="最近 N 天，覆盖分类默认值"),
    take: int = Query(default=100, le=500),
    min_score: float = Query(default=6.0),
    q: Optional[str] = None,
):
    """获取情报条目列表。

    时间窗口逻辑：
    - 如果传了 days，全局覆盖所有分类的时间窗口
    - 如果没传 days，使用每个分类各自的 freshness_days
    """
    from engine.domain import load_domain
    s = get_store()

    # 加载领域配置获取分类时间窗口
    try:
        dc = load_domain(domain)
        cat_freshness = dc.category_freshness
    except Exception:
        cat_freshness = {}

    # 全局 days 覆盖
    global_since = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        global_since = cutoff.isoformat()

    if mode == "selected":
        if category or global_since or since:
            # 单分类或全局时间窗口：直接查询
            published_since = global_since
            if not published_since and category and not since:
                cat_days = cat_freshness.get(category, 7)
                cutoff = datetime.now(timezone.utc) - timedelta(days=cat_days)
                published_since = cutoff.isoformat()
            items = s.get_selected(
                domain=domain, since=since, category=category,
                take=take, min_score=min_score,
                published_since=published_since, q=q,
            )
        else:
            # 无筛选：按分类各自的时间窗口合并
            all_items = []
            seen_ids = set()
            for cat_id, cat_days in cat_freshness.items():
                cutoff = datetime.now(timezone.utc) - timedelta(days=cat_days)
                cat_items = s.get_selected(
                    domain=domain, category=cat_id,
                    take=take, min_score=min_score,
                    published_since=cutoff.isoformat(), q=q,
                )
                for item in cat_items:
                    item_id = item.get("id")
                    if item_id not in seen_ids:
                        seen_ids.add(item_id)
                        all_items.append(item)
            # 无分类配置的条目
            other_items = s.get_selected(
                domain=domain, take=take, min_score=min_score, q=q,
            )
            for item in other_items:
                item_id = item.get("id")
                if item_id not in seen_ids:
                    seen_ids.add(item_id)
                    all_items.append(item)
            all_items.sort(key=lambda x: x.get("score", 0), reverse=True)
            items = all_items[:take]
    else:
        published_since = global_since
        items = s.get_all(
            domain=domain, since=since, category=category, take=take,
            published_since=published_since, q=q,
        )

    # 按 source_id 过滤（后处理）
    if source_id:
        items = [i for i in items if i.get("source_id") == source_id]

    # 注入 source_name
    src_map = _get_source_map(domain)
    for item in items:
        item["source_name"] = src_map.get(item.get("source_id", ""), "")

    return {"domain": domain, "mode": mode, "count": len(items), "items": items, "category_freshness": cat_freshness}


@app.get("/api/stats")
def get_stats(domain: str = Query(default="elderly-care")):
    """获取统计概览。"""
    s = get_store()
    return s.get_stats(domain)


@app.get("/api/categories")
def get_categories(domain: str = Query(default="elderly-care")):
    """获取分类列表及各分类条目数（含时间窗口配置）。"""
    from engine.domain import load_domain
    s = get_store()

    # 加载分类配置
    try:
        dc = load_domain(domain)
        cat_freshness = dc.category_freshness
        cat_names = {c["id"]: c["name"] for c in dc.categories.get("categories", [])}
    except Exception:
        cat_freshness = {}
        cat_names = {}

    # 查询各分类在各自时间窗口内的条目数
    result = []
    for cat_id, cat_days in cat_freshness.items():
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=cat_days)
        rows = s.conn.execute(
            """SELECT COUNT(*) as cnt, AVG(score) as avg_score
               FROM scored_items
               WHERE domain = ? AND category = ? AND score >= 6.0
               AND created_at >= ?""",
            (domain, cat_id, cutoff.isoformat()),
        ).fetchall()
        cnt = rows[0]["cnt"] if rows else 0
        avg = rows[0]["avg_score"] if rows and rows[0]["avg_score"] else 0
        result.append({
            "id": cat_id,
            "name": cat_names.get(cat_id, cat_id),
            "cnt": cnt,
            "avg_score": round(avg, 1) if avg else 0,
            "freshness_days": cat_days,
        })

    return {"categories": result}


@app.get("/api/sources")
def get_sources(domain: str = Query(default="elderly-care")):
    """获取信源列表及各信源条目数（含名称和健康状态）。"""
    from engine.evolution.source_analyzer import analyze_source_quality
    s = get_store()
    src_map = _get_source_map(domain)

    rows = s.conn.execute(
        """SELECT source_id, COUNT(*) as cnt
           FROM raw_items GROUP BY source_id ORDER BY cnt DESC""",
    ).fetchall()

    # 信源健康状态
    try:
        health_data = analyze_source_quality(domain, days=7)
        health_map = {h["source_id"]: h["status"] for h in health_data.get("sources", [])}
    except Exception:
        health_map = {}

    sources = []
    for r in rows:
        d = dict(r)
        d["name"] = src_map.get(d["source_id"], d["source_id"])
        d["health"] = health_map.get(d["source_id"], "unknown")
        sources.append(d)

    return {"sources": sources}


@app.get("/api/report/{date}")
def get_report(date: str, domain: str = Query(default="elderly-care")):
    """获取指定日期的日报 JSON。"""
    json_path = settings.project_root / settings.report_dir / f"{date}-{domain}.json"
    if not json_path.exists():
        return {"error": f"未找到 {date} 的日报"}
    return json.loads(json_path.read_text(encoding="utf-8"))


@app.get("/api/evolution")
def get_evolution(domain: str = Query(default="elderly-care"), days: int = Query(default=7)):
    """获取进化分析数据（信源健康 + 评分分布 + 关键词建议）。"""
    from engine.evolution.source_analyzer import analyze_source_quality
    from engine.evolution.scoring_calibrator import analyze_scoring_distribution, suggest_adjustments
    from engine.evolution.keyword_expander import suggest_new_keywords

    try:
        source_health = analyze_source_quality(domain, days)
    except Exception:
        source_health = {"sources": []}

    try:
        scoring = analyze_scoring_distribution(domain, days)
        adjustments = suggest_adjustments(domain, days)
    except Exception:
        scoring = {"overall": {}}
        adjustments = []

    try:
        kw_suggestions = suggest_new_keywords(domain, days)
    except Exception:
        kw_suggestions = []

    return {
        "domain": domain,
        "days": days,
        "source_health": source_health,
        "scoring": scoring,
        "scoring_adjustments": adjustments,
        "keyword_suggestions": kw_suggestions,
    }


@app.get("/api/trending")
def get_trending(domain: str = Query(default="elderly-care"), take: int = Query(default=10, le=50)):
    """获取热门条目（高分 + 高引用实体）。"""
    s = get_store()
    rows = s.conn.execute(
        """SELECT s.*, r.title, r.url, r.content, r.published, r.source_id
           FROM scored_items s
           JOIN raw_items r ON s.raw_id = r.id
           WHERE s.domain = ? AND s.score >= 7.0
           ORDER BY s.score DESC LIMIT ?""",
        (domain, take),
    ).fetchall()
    items = [dict(r) for r in rows]
    src_map = _get_source_map(domain)
    for item in items:
        item["source_name"] = src_map.get(item.get("source_id", ""), "")
    return {"items": items}


# ── SKILL 接入 ──

@app.get("/skill/{skill_name}/SKILL.md", response_class=HTMLResponse)
def skill_md(skill_name: str = "china-africa"):
    """提供 SKILL.md 供 Agent 安装。"""
    path = settings.project_root / "skills" / skill_name / "SKILL.md"
    if path.exists():
        return HTMLResponse(path.read_text(encoding="utf-8"))
    return HTMLResponse(f"SKILL.md not found for {skill_name}", status_code=404)


@app.get("/skill/{skill_name}/install.sh", response_class=HTMLResponse)
def skill_install(skill_name: str = "china-africa"):
    """一键安装脚本。"""
    script = f'''#!/bin/bash
# {{skill_name}} Skill 安装脚本
set -e

SKILL_DIR="${{HOME}}/.claude/skills/{{skill_name}}"
mkdir -p "$SKILL_DIR"

curl -fsSL "https://intel-pipeline.local/skill/{{skill_name}}/SKILL.md" -o "$SKILL_DIR/SKILL.md"
echo "{{skill_name}} Skill 已安装到 $SKILL_DIR"
echo "在 Agent 中使用即可"
'''
    return HTMLResponse(script, media_type="text/plain")


# ── 前端页面 ──

@app.get("/", response_class=HTMLResponse)
def index():
    """主页：统一情报面板。"""
    template_path = settings.project_root / "engine" / "output" / "templates" / "dashboard.html"
    if template_path.exists():
        return HTMLResponse(template_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Intel Pipeline</h1><p>Dashboard template not found.</p>")


@app.get("/health")
def health():
    return {"status": "ok", "domain": settings.domain}


# ── RSS Feeds ──

@app.get("/rss/curated", response_class=Response)
def rss_curated(domain: str = Query(default="elderly-care")):
    """RSS Feed：精选情报。"""
    s = get_store()
    items = s.get_selected(domain, take=50, min_score=6.0)
    return _build_rss(f"{domain} 情报 - 精选", f"{domain} 精选情报 Feed", items, domain)


@app.get("/rss/all", response_class=Response)
def rss_all(domain: str = Query(default="elderly-care")):
    """RSS Feed：全部情报。"""
    s = get_store()
    items = s.get_all(domain, take=100)
    return _build_rss(f"{domain} 情报 - 全部", f"{domain} 全部情报 Feed", items, domain)


@app.get("/rss/daily", response_class=Response)
def rss_daily(domain: str = Query(default="elderly-care")):
    """RSS Feed：今日日报。"""
    date = datetime.now().strftime("%Y-%m-%d")
    json_path = settings.project_root / settings.report_dir / f"{date}-{domain}.json"
    if not json_path.exists():
        items = get_store().get_selected(domain, take=50, min_score=6.0)
    else:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return _build_rss(f"{domain} 日报 - {date}", f"{domain} {date} 情报日报", data.get("items", []), domain)
    return _build_rss(f"{domain} 日报 - {date}", f"{domain} {date} 情报日报", items, domain)


def _build_rss(title: str, description: str, items: list[dict], domain: str) -> Response:
    """构建 RSS 2.0 XML。"""
    from datetime import timezone
    now = datetime.now(timezone.utc)
    now_rfc = now.strftime("%a, %d %b %Y %H:%M:%S +0000")

    xml = [f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>{_xml_escape(title)}</title>
  <link>http://localhost:8900/</link>
  <description>{_xml_escape(description)}</description>
  <language>zh-cn</language>
  <lastBuildDate>{now_rfc}</lastBuildDate>
  <atom:link href="/rss/curated" rel="self" type="application/rss+xml"/>''']

    for item in items:
        item_title = item.get("title", "") or item.get("raw", {}).get("title", "")
        item_url = item.get("url", "") or item.get("raw", {}).get("url", "")
        item_summary = item.get("summary", "") or ""
        item_score = item.get("score", 0)
        item_pub = item.get("published", "") or ""

        pub_rfc = ""
        if item_pub:
            try:
                dt = datetime.fromisoformat(str(item_pub).replace("Z", "+00:00"))
                pub_rfc = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
            except Exception:
                pass

        guid = item.get("id", item_url) or item_url

        xml.append(f'''  <item>
    <title>{_xml_escape(item_title)}</title>
    <link>{_xml_escape(item_url)}</link>
    <guid isPermaLink="false">{_xml_escape(str(guid))}</guid>
    <description>{_xml_escape(f"[{item_score}] {item_summary}")}</description>
    {f"<pubDate>{pub_rfc}</pubDate>" if pub_rfc else ""}
  </item>''')

    xml.append("</channel>\n</rss>")

    return Response(
        content="\n".join(xml),
        media_type="application/xml",
        headers={"Cache-Control": "no-cache"},
    )


def _xml_escape(s: str) -> str:
    """XML 转义。"""
    if not s:
        return ""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace('"', "&quot;").replace("'", "&apos;")
    return s[:2000]


def start_api():
    """启动 API 服务。"""
    import uvicorn
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
