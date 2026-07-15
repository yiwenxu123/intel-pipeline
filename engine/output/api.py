"""REST API 服务：对外暴露情报查询接口，同时托管前端页面。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from engine.config import settings
from engine.output.auth import verify_write_token
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

# 挂载静态文件（离线 tailwind 等）
_static_dir = settings.project_root / "engine" / "output" / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

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
    date: Optional[str] = Query(default=None, description="按发布日期精确过滤 YYYY-MM-DD"),
    take: int = Query(default=100, le=500),
    min_score: float = Query(default=5.5),
    q: Optional[str] = None,
):
    """获取情报条目列表。

    时间窗口逻辑：
    - 如果传了 date，按该日期精确过滤（优先级最高）
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

    # date 模式：按日期精确过滤，跳过所有 days/since 逻辑
    if date:
        if mode == "selected":
            items = s.get_selected(
                domain=domain, take=take, published_date=date,
                category=category, q=q, min_score=min_score,
            )
        else:
            items = s.get_all(
                domain=domain, take=take, published_date=date,
                category=category, q=q,
            )
        # 注入 source_name
        src_map = _get_source_map(domain)
        for item in items:
            item["source_name"] = src_map.get(item.get("source_id", ""), "")
        if source_id:
            items = [i for i in items if i.get("source_id") == source_id]
        return {"domain": domain, "mode": mode, "count": len(items), "items": items,
                "category_freshness": cat_freshness, "date": date}

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


@app.get("/api/dates")
def get_dates(domain: str = Query(default="elderly-care")):
    """获取有精选条目的日期列表（降序），用于日期导航。"""
    s = get_store()
    dates = s.get_available_dates(domain, min_score=5.5, limit=30)
    return {"domain": domain, "dates": dates}


@app.get("/api/stats")
def get_stats(domain: str = Query(default="elderly-care")):
    """获取统计概览。"""
    s = get_store()
    return s.get_stats(domain)


@app.get("/api/trends")
def get_trends(domain: str = Query(default="elderly-care"), days: int = Query(default=30, le=365)):
    """获取评分趋势（按周/月聚合 + 分类分布）。"""
    s = get_store()
    return s.get_trends(domain, days)


@app.get("/api/categories")
def get_categories(domain: str = Query(default="elderly-care")):
    """获取分类列表及各分类条目数（含时间窗口配置）。"""
    from engine.domain import load_domain
    s = get_store()

    from engine.output.category_colors import color_for

    try:
        dc = load_domain(domain)
        cat_freshness = dc.category_freshness
        cat_meta = {c["id"]: c for c in dc.categories.get("categories", [])}
    except Exception:
        cat_freshness = {}
        cat_meta = {}

    stats = s.get_category_stats(domain, cat_freshness)
    result = [
        {
            "id": st["id"],
            "name": cat_meta.get(st["id"], {}).get("name", st["id"]),
            "cnt": st["cnt"],
            "avg_score": st["avg_score"],
            "freshness_days": cat_freshness.get(st["id"], 7),
            "color": color_for(st["id"], cat_meta.get(st["id"], {}).get("color")),
        }
        for st in stats
    ]
    return {"categories": result}


@app.get("/api/sources")
def get_sources(domain: str = Query(default="elderly-care")):
    """获取信源列表及各信源条目数（含名称和健康状态）。"""
    from engine.evolution.source_analyzer import analyze_source_quality
    s = get_store()
    src_map = _get_source_map(domain)

    rows = s.get_source_stats()

    try:
        health_data = analyze_source_quality(domain, days=7)
        health_map = {h["source_id"]: h["status"] for h in health_data.get("sources", [])}
    except Exception:
        health_map = {}

    sources = []
    for r in rows:
        r["name"] = src_map.get(r["source_id"], r["source_id"])
        r["health"] = health_map.get(r["source_id"], "unknown")
        sources.append(r)

    return {"sources": sources}


@app.get("/api/report/{date}")
def get_report(date: str, domain: str = Query(default="elderly-care")):
    """获取指定日期的日报 JSON。"""
    json_path = settings.project_root / settings.report_dir / f"{date}-{domain}.json"
    if not json_path.exists():
        return {"error": f"未找到 {date} 的日报"}
    return json.loads(json_path.read_text(encoding="utf-8"))


@app.get("/api/llm-usage")
def llm_usage(domain: str = Query(default="elderly-care"), days: int = Query(default=30)):
    """获取 LLM 调用用量历史。"""
    s = get_store()
    return s.get_llm_usage(domain, days)


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


@app.get("/api/health")
def get_health(domain: str = Query(default="elderly-care"), days: int = Query(default=7)):
    """获取系统健康状态。"""
    from engine.evolution.source_analyzer import analyze_source_quality
    from engine.evolution.source_lifecycle import get_lifecycle_status
    from engine.evolution.scoring_calibrator import analyze_scoring_distribution
    from engine.evolution.keyword_staging import get_staging

    s = get_store()

    # 信源健康度
    try:
        source_health = analyze_source_quality(domain, days)
        healthy_count = len([src for src in source_health.get("sources", []) if src["status"] == "healthy"])
        total_count = len(source_health.get("sources", []))
    except Exception:
        source_health = {"sources": []}
        healthy_count = 0
        total_count = 0

    # 信源生命周期状态
    try:
        lifecycle_status = get_lifecycle_status(domain)
    except Exception:
        lifecycle_status = []

    # 评分分布
    try:
        scoring = analyze_scoring_distribution(domain, days)
    except Exception:
        scoring = {"overall": {}}

    # 关键词暂存状态
    try:
        keyword_staging = get_staging(domain)
    except Exception:
        keyword_staging = None

    # 统计数据
    stats = s.get_stats(domain)

    return {
        "domain": domain,
        "days": days,
        "source_health": {
            "healthy_count": healthy_count,
            "total_count": total_count,
            "sources": source_health.get("sources", []),
        },
        "lifecycle_status": lifecycle_status,
        "scoring": scoring,
        "keyword_staging": keyword_staging,
        "stats": stats,
    }


@app.get("/api/config")
def api_config():
    """公开配置（不含密钥）。"""
    return {
        "auth_required": bool(settings.api_token),
        "domain": settings.domain,
    }


@app.post("/api/items/feedback", dependencies=[Depends(verify_write_token)])
def submit_feedback(
    raw_id: int = Query(..., description="raw_items 的 ID"),
    domain: str = Query(default="elderly-care"),
    corrected_score: float = Query(..., ge=0, le=10),
    reason: str = Query(default=""),
):
    s = get_store()
    row = s.conn.execute(
        "SELECT score FROM scored_items WHERE raw_id = ? AND domain = ? ORDER BY created_at DESC LIMIT 1",
        (raw_id, domain),
    ).fetchone()
    if not row:
        return {"success": False, "error": "未找到该条目的评分记录"}
    original_score = row["score"]
    feedback_id = s.save_feedback(raw_id, domain, original_score, corrected_score, reason)
    return {
        "success": True,
        "feedback_id": feedback_id,
        "original_score": original_score,
        "corrected_score": corrected_score,
    }


@app.get("/api/items/feedback-stats")
def feedback_stats(domain: str = Query(default="elderly-care"), days: int = Query(default=7)):
    s = get_store()
    stats = s.get_feedback_stats(domain, days)
    return {"domain": domain, "days": days, **stats}


@app.post("/api/sources/{source_id}/confirm", dependencies=[Depends(verify_write_token)])
def confirm_source(source_id: str, domain: str = Query(default="elderly-care")):
    """人工确认信源状态（标记为已确认，不会被自动禁用）。"""
    from engine.evolution.source_lifecycle import confirm_source_status

    try:
        result = confirm_source_status(domain, source_id)
        return {"success": True, "source_id": source_id, "confirmed": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/sources/{source_id}/disable", dependencies=[Depends(verify_write_token)])
def disable_source(source_id: str, domain: str = Query(default="elderly-care")):
    """手动禁用信源。"""
    from engine.evolution.source_lifecycle import manual_disable_source

    try:
        result = manual_disable_source(domain, source_id)
        return {"success": True, "source_id": source_id, "disabled": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/sources/{source_id}/enable", dependencies=[Depends(verify_write_token)])
def enable_source(source_id: str, domain: str = Query(default="elderly-care")):
    """手动启用信源。"""
    from engine.evolution.source_lifecycle import manual_enable_source

    try:
        result = manual_enable_source(domain, source_id)
        return {"success": True, "source_id": source_id, "enabled": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


_DOMAIN_LABELS = {
    "elderly-care": {"name": "银发产业", "port": 8901},
    "china-africa": {"name": "中非经贸", "port": 8900},
}


@app.get("/api/overview")
def api_overview():
    """多领域总览：今日精选、周趋势、LLM 成本。"""
    domains_dir = settings.project_root / "domains"
    today = datetime.now().strftime("%Y-%m-%d")
    cards = []

    for domain_dir in sorted(domains_dir.iterdir()):
        if not domain_dir.is_dir() or not (domain_dir / "sources.yaml").exists():
            continue
        domain = domain_dir.name
        meta = _DOMAIN_LABELS.get(domain, {"name": domain, "port": settings.api_port})
        db_path = settings.project_root / f"data/intel-{domain}.db"
        if not db_path.exists():
            cards.append({
                "domain": domain,
                "name": meta["name"],
                "port": meta["port"],
                "today_selected": 0,
                "total_selected": 0,
                "narrative": "",
                "llm_cost_month_cny": 0,
                "has_data": False,
            })
            continue

        with Store(db_path=db_path) as store:
            stats = store.get_stats(domain)
            today_row = store.conn.execute(
                """SELECT COUNT(*) as c FROM scored_items
                   WHERE domain = ? AND created_at LIKE ? AND score >= 5.5""",
                (domain, f"{today}%"),
            ).fetchone()
            change = store.get_change_narrative(domain)
            fb = store.get_feedback_stats(domain, days=7)
            sel = stats.get("selected", 0) or 0
            brief_row = store.conn.execute(
                """SELECT COUNT(*) c FROM scored_items
                   WHERE domain=? AND score>=6 AND headline IS NOT NULL AND headline!=''""",
                (domain,),
            ).fetchone()
            brief_n = brief_row["c"] if brief_row else 0
            cards.append({
                "domain": domain,
                "name": meta["name"],
                "port": meta["port"],
                "today_selected": today_row["c"] if today_row else 0,
                "total_selected": sel,
                "last_fetch_time": stats.get("last_fetch_time"),
                "unscored_count": stats.get("unscored_count", 0),
                "briefing_coverage_pct": round(100.0 * brief_n / max(sel, 1), 1),
                "feedback_7d": fb,
                "narrative": change.get("narrative", ""),
                "llm_cost_month_cny": stats.get("llm_cost_month_cny", 0),
                "has_data": True,
            })

    return {"date": today, "domains": cards}


@app.get("/api/export")
def export_items(
    domain: str = Query(default="elderly-care"),
    days: int = Query(default=7, le=90),
    min_score: float = Query(default=5.5),
    fmt: str = Query(default="markdown", alias="format", description="markdown / json"),
):
    """导出精选列表（Markdown 或 JSON）。"""
    s = get_store()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    items = s.get_selected(domain, since=cutoff, take=200, min_score=min_score)
    src_map = _get_source_map(domain)
    for item in items:
        item["source_name"] = src_map.get(item.get("source_id", ""), "")

    if fmt == "json":
        return {"domain": domain, "days": days, "count": len(items), "items": items}

    lines = [
        f"# {domain} 精选情报导出",
        "",
        f"- 导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 范围：最近 {days} 天，≥{min_score} 分，共 {len(items)} 条",
        "",
    ]
    for i, item in enumerate(items, 1):
        title = item.get("title_display") or item.get("title", "")
        lines.extend([
            f"## {i}. [{item.get('score', 0):.1f}] {title}",
            "",
            f"- 分类：{item.get('category', '')}",
            f"- 信源：{item.get('source_name') or item.get('source_id', '')}",
            f"- 链接：{item.get('url', '')}",
            f"- 摘要：{item.get('summary', '')}",
            "",
        ])
    content = "\n".join(lines)
    filename = f"export-{domain}-{datetime.now().strftime('%Y%m%d')}.md"
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    script = '''#!/bin/bash
# {skill_name} Skill 安装脚本
set -e

SKILL_DIR="${HOME}/.claude/skills/{skill_name}"
mkdir -p "$SKILL_DIR"

curl -fsSL "https://intel-pipeline.local/skill/{skill_name}/SKILL.md" -o "$SKILL_DIR/SKILL.md"
echo "{skill_name} Skill 已安装到 $SKILL_DIR"
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
    items = s.get_selected(domain, take=50, min_score=5.5)
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
        items = get_store().get_selected(domain, take=50, min_score=5.5)
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
    import logging
    import uvicorn

    if not settings.api_token:
        logging.getLogger(__name__).warning(
            "INTEL_API_TOKEN 未配置，所有写操作无鉴权保护！建议在内网环境使用。"
        )
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
