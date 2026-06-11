"""内部产品级 DoD 质量指标。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.config import settings
from engine.store import Store

# DoD 目标值
DOD_TARGETS = {
    "unscored_count": 50,
    "briefing_coverage_pct": 80.0,
    "false_positive_rate_pct": 20.0,
    "pipe_success_rate_pct": 95.0,
    "fetch_errors_per_run": 3,
}


def compute_quality_metrics(domain: str, store: Store | None = None) -> dict:
    """计算路线图 DoD 相关指标。"""
    own_store = store is None
    s = store or Store()
    try:
        stats = s.get_stats(domain)
        unscored = stats.get("unscored_count", 0)

        sel_row = s.conn.execute(
            "SELECT COUNT(*) c FROM scored_items WHERE domain=? AND score>=6",
            (domain,),
        ).fetchone()
        selected = sel_row["c"] if sel_row else 0

        brief_row = s.conn.execute(
            """SELECT COUNT(*) c FROM scored_items
               WHERE domain=? AND score>=6 AND headline IS NOT NULL AND headline!=''""",
            (domain,),
        ).fetchone()
        with_brief = brief_row["c"] if brief_row else 0
        briefing_pct = round(100.0 * with_brief / max(selected, 1), 1)

        rejected = s.conn.execute(
            "SELECT COUNT(*) c FROM scored_items WHERE domain=? AND category='rejected'",
            (domain,),
        ).fetchone()["c"]

        pipe_stats = _pipe_success_rate(s, domain, days=7)
        feedback = s.get_feedback_stats(domain, days=7)

        bands = s.conn.execute(
            """SELECT
                 SUM(CASE WHEN score>=8 THEN 1 ELSE 0 END) b8,
                 SUM(CASE WHEN score>=6 AND score<8 THEN 1 ELSE 0 END) b6,
                 SUM(CASE WHEN score>=4 AND score<6 THEN 1 ELSE 0 END) b4,
                 SUM(CASE WHEN score<4 THEN 1 ELSE 0 END) b0,
                 COUNT(*) total
               FROM scored_items WHERE domain=?""",
            (domain,),
        ).fetchone()

        dod = {
            "D1_unscored_ok": unscored < DOD_TARGETS["unscored_count"],
            "D2_briefing_ok": briefing_pct >= DOD_TARGETS["briefing_coverage_pct"],
            "D4_pipe_ok": pipe_stats["success_rate_pct"] >= DOD_TARGETS["pipe_success_rate_pct"]
            if pipe_stats["total_runs"] > 0
            else None,
            "D5_last_fetch_errors_ok": (stats.get("last_fetch_errors") or 0)
            < DOD_TARGETS["fetch_errors_per_run"],
            "D8_api_token": bool(settings.api_token),
        }

        return {
            "domain": domain,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "targets": DOD_TARGETS,
            "metrics": {
                "unscored_count": unscored,
                "selected_count": selected,
                "briefing_coverage_pct": briefing_pct,
                "briefing_with_headline": with_brief,
                "rule_rejected_count": rejected,
                "total_scored": bands["total"] or 0,
                "score_bands": {
                    "8+": bands["b8"] or 0,
                    "6-8": bands["b6"] or 0,
                    "4-6": bands["b4"] or 0,
                    "<4": bands["b0"] or 0,
                },
                "pipe_7d": pipe_stats,
                "feedback_7d": feedback,
                "last_pipe_at": stats.get("last_pipe_at"),
                "last_fetch_errors": stats.get("last_fetch_errors"),
            },
            "dod": dod,
        }
    finally:
        if own_store:
            s.close()


def _pipe_success_rate(store: Store, domain: str, days: int = 7) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = store.conn.execute(
        "SELECT error FROM pipe_runs WHERE domain=? AND created_at>=?",
        (domain, cutoff),
    ).fetchall()
    total = len(rows)
    if total == 0:
        return {"total_runs": 0, "success_runs": 0, "success_rate_pct": 0.0}
    ok = sum(1 for r in rows if not r["error"])
    return {
        "total_runs": total,
        "success_runs": ok,
        "success_rate_pct": round(100.0 * ok / total, 1),
    }
