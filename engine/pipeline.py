"""完整情报管道：fetch → filter → report → notify。

CLI 和 scheduler 共同调用此模块，避免代码重复。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from engine.config import settings
from engine.domain import DomainConfig
from engine.fetcher.runner import fetch_all
from engine.models import RawItem, ScoredItem, FetchResult, FilterResult
from engine.store import Store

logger = logging.getLogger(__name__)


class PipelineResult:
    """管道执行结果。"""

    def __init__(self):
        self.fetch: FetchResult | None = None
        self.filter: FilterResult | None = None
        self.report_path: str | None = None
        self.lifecycle: dict | None = None
        self.notified: bool = False
        self.error: str | None = None
        self.duration_seconds: float = 0.0


def run_full_pipeline(domain: DomainConfig, notify: bool = True, max_items: int = 50) -> PipelineResult:
    """执行完整管道：采集 → 筛选 → 日报 → 推送。

    Args:
        notify: 是否在完成后推送飞书通知（默认 True）。
        max_items: 每次筛选的最大条目数（默认 50）。
    """
    result = PipelineResult()
    start = time.time()

    # ── 1. 采集 ──
    try:
        with Store() as store:
            result.fetch = fetch_all(domain, store)
        fr = result.fetch
        logger.info(f"[{domain.name}] 采集完成: 新增 {len(fr.new_items)} 条, "
                     f"信源 {fr.sources_success}/{fr.sources_total}, 耗时 {fr.duration_seconds}s")
        for err in fr.errors:
            logger.warning(f"[{domain.name}] 信源 {err.source_id} 采集失败: {err.error}")
    except Exception as e:
        logger.error(f"[{domain.name}] 采集阶段失败: {e}")
        result.error = f"采集失败: {e}"
        result.duration_seconds = time.time() - start
        _record_pipe_run(domain.name, result)
        _maybe_pipe_alert(domain.name, result)
        return result

    # ── 2. 筛选 ──
    filter_start = time.time()
    try:
        with Store() as store:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.score_window_days)).isoformat()
            # 优化筛选逻辑：
            # 1. 优先筛选有 published 日期且在窗口内的条目
            # 2. 对于没有 published 日期的条目，使用 fetched_at 替代
            # 3. 对于日期明显错误的条目（如 2017 年），使用 fetched_at 替代
            rows = store.conn.execute(
                """SELECT r.* FROM raw_items r
                   WHERE (
                       (r.published >= ? AND r.published >= '2020-01-01')
                       OR (r.published IS NULL AND r.fetched_at >= ?)
                       OR (r.published < '2020-01-01' AND r.fetched_at >= ?)
                   )
                   AND r.id NOT IN (SELECT raw_id FROM scored_items WHERE domain = ?)
                   ORDER BY COALESCE(r.published, r.fetched_at) DESC
                   LIMIT ?""",
                (cutoff, cutoff, cutoff, domain.name, max_items),
            ).fetchall()

            if rows:
                items = [
                    RawItem(
                        source_id=r["source_id"], title=r["title"], url=r["url"],
                        content=r["content"] or "", lang=r["lang"] or "zh",
                        full_text=r["full_text"],
                    )
                    for r in rows
                ]
                from engine.filter.llm_client import reset_usage, get_usage
                from engine.filter.runner import filter_and_score

                reset_usage()
                unscored_total = store.get_unscored_count(domain.name, settings.score_window_days)
                if unscored_total >= settings.unscored_warn_threshold:
                    logger.info(f"[{domain.name}] 待评分积压 {unscored_total} 条")

                scored, flt_result = filter_and_score(items, domain, store)
                for si in scored:
                    raw_id = store.save_raw(si.raw)
                    store.save_scored(raw_id, domain.name, si)
                result.filter = flt_result
                filter_duration = time.time() - filter_start
                usage = get_usage()
                try:
                    store.save_llm_usage(
                        domain.name, usage["calls"], usage["input_tokens"],
                        usage["output_tokens"], filter_duration, len(scored),
                    )
                except Exception as e:
                    logger.warning(f"[{domain.name}] LLM 用量持久化失败: {e}")
                logger.info(f"[{domain.name}] 筛选完成: {len(scored)}/{len(items)} 条")
            else:
                logger.info(f"[{domain.name}] 无待筛选条目")
    except Exception as e:
        logger.error(f"[{domain.name}] 筛选阶段失败: {e}")
        result.error = f"筛选失败: {e}"
        result.duration_seconds = time.time() - start
        _record_pipe_run(domain.name, result)
        _maybe_pipe_alert(domain.name, result)
        return result

    # ── 3. 日报（只包含昨日的条目） ──
    try:
        from engine.output.report import generate_report, save_report, compute_trend_text
        with Store() as store:
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            rows = store.get_selected(domain.name, take=100, min_score=6.0, published_date=yesterday)
            if rows:
                items = []
                for r in rows:
                    raw = RawItem(source_id=r["source_id"], title=r["title"],
                                  url=r["url"], content=r.get("content", ""),
                                  full_text=r.get("full_text"),
                                  published=r.get("published"))
                    import json as _json
                    kp = r.get("key_points", "[]")
                    if isinstance(kp, str):
                        try:
                            kp = _json.loads(kp)
                        except Exception:
                            kp = []
                    items.append(ScoredItem(
                        raw=raw, score=r["score"], category=r.get("category", ""),
                        summary=r.get("summary", ""), reason=r.get("reason", ""),
                        key_points=kp if isinstance(kp, list) else [],
                        title_display=r.get("title_display", "") or "",
                        headline=r.get("headline", "") or "",
                        lead=r.get("lead", "") or "",
                        takeaway=r.get("takeaway", "") or "",
                        insight_type=r.get("insight_type", "fact") or "fact",
                        content_type=r.get("content_type", "news") or "news",
                    ))
                stats = store.get_stats(domain.name)
                trend_text = compute_trend_text(store, domain.name)
                report = generate_report(items, domain, total_fetched=stats.get("total_fetched", 0),
                                         trend_text=trend_text)
                md_path, json_path = save_report(report)
                result.report_path = str(md_path)
                logger.info(f"[{domain.name}] 日报已生成: {md_path}")
            else:
                logger.info(f"[{domain.name}] 无精选条目，跳过日报")
    except Exception as e:
        logger.error(f"[{domain.name}] 日报阶段失败: {e}")

    # ── 4. 生命周期检查（信源度量 + 自动降级） ──
    try:
        from engine.evolution.source_lifecycle import run_lifecycle_check
        lifecycle = run_lifecycle_check(domain.name)
        result.lifecycle = lifecycle
        if lifecycle.get("disabled"):
            logger.warning(f"[{domain.name}] 自动降级 {len(lifecycle['disabled'])} 个信源: {lifecycle['disabled']}")
        else:
            logger.info(f"[{domain.name}] 生命周期检查完成，无降级")
    except Exception as e:
        logger.error(f"[{domain.name}] 生命周期检查失败: {e}")

    # ── 4.5 关键词暂存验证 ──
    try:
        from engine.evolution.keyword_staging import get_staged_keywords, record_trial_result, check_and_apply
        staged_kws = get_staged_keywords(domain.name)
        if staged_kws and result.filter:
            # 用当前通过率与历史平均对比
            current_rate = result.filter.pre_filter_passed / max(result.filter.pre_filter_total, 1)
            with Store() as store:
                hist = store.conn.execute(
                    "SELECT AVG(yield_rate) as avg FROM source_metrics WHERE domain = ?",
                    (domain.name,),
                ).fetchone()
            hist_avg = hist["avg"] if hist and hist["avg"] else 0.05
            # 如果当前通过率高于历史平均，接受暂存关键词
            record_trial_result(domain.name, current_rate, hist_avg)
            kw_result = check_and_apply(domain.name)
            if kw_result.get("action") == "applied":
                logger.info(f"[{domain.name}] 关键词自动验证通过，已合并 {len(kw_result.get('keywords', []))} 个")
            elif kw_result.get("action") == "rejected":
                logger.info(f"[{domain.name}] 关键词自动验证未通过，已回滚")
    except Exception as e:
        logger.error(f"[{domain.name}] 关键词验证失败: {e}")

    # ── 4.6 评分校准检查 ──
    try:
        from engine.evolution.scoring_injector import run_calibration_check
        cal_result = run_calibration_check(domain.name, days=7)
        cal_count = len(cal_result.get("calibrations", []))
        if cal_count > 0:
            logger.info(f"[{domain.name}] 生成 {cal_count} 条评分校准指令，下次评分自动注入")
            if settings.notify_webhook:
                try:
                    from engine.output.notifier import notify_scoring_calibration
                    notify_scoring_calibration(domain.name, cal_result.get("calibrations", []))
                except Exception as notify_err:
                    logger.warning(f"[{domain.name}] 评分校准推送失败: {notify_err}")
        else:
            logger.info(f"[{domain.name}] 评分分布正常，无需校准")
    except Exception as e:
        logger.error(f"[{domain.name}] 评分校准检查失败: {e}")

    # ── 5. 推送通知 ──
    if notify:
        try:
            if settings.notify_webhook:
                from engine.output.notifier import notify_report
                with Store() as store:
                    selected = store.get_selected(domain.name, take=5, min_score=6.0)
                    stats = store.get_stats(domain.name)
                    report_json = None
                    if result.report_path:
                        from pathlib import Path
                        json_path = Path(result.report_path).with_suffix(".json")
                        if json_path.exists():
                            import json as _json
                            report_json = _json.loads(json_path.read_text(encoding="utf-8"))
                notify_report(domain.name, stats, selected, report_extra=report_json)
                result.notified = True
                logger.info(f"[{domain.name}] 推送通知已发送")
        except Exception as e:
            logger.error(f"[{domain.name}] 推送通知失败: {e}")

    result.duration_seconds = round(time.time() - start, 2)
    _record_pipe_run(domain.name, result)
    _record_daily_snapshot(domain.name)
    _maybe_pipe_alert(domain.name, result)
    _maybe_unscored_warning(domain.name)
    return result


def _maybe_pipe_alert(domain_name: str, result: PipelineResult) -> None:
    """pipe 失败或采集错误过多时推送告警（独立于日报 notify）。"""
    try:
        from engine.config import settings
        if not settings.notify_webhook:
            return
        fr = result.fetch
        error_count = len(fr.errors) if fr and fr.errors else 0
        if not result.error and error_count < settings.pipe_alert_error_threshold:
            return
        from engine.output.notifier import notify_pipe_alert
        notify_pipe_alert(
            domain_name,
            error=result.error,
            fetch_errors=error_count,
            fetch_error_sources=[e.source_id for e in fr.errors] if fr and fr.errors else [],
            duration_seconds=result.duration_seconds,
            scored=result.filter.scored_total if result.filter else 0,
        )
    except Exception as e:
        logger.warning(f"[{domain_name}] 管道告警推送失败: {e}")


def _maybe_unscored_warning(domain_name: str) -> None:
    """待评分堆积超阈值时日志警告，可选推送。"""
    try:
        from engine.config import settings
        with Store() as store:
            unscored = store.get_unscored_count(domain_name, settings.score_window_days)
        if unscored < settings.unscored_warn_threshold:
            return
        logger.warning(
            f"[{domain_name}] 待评分堆积 {unscored} 条（阈值 {settings.unscored_warn_threshold}），"
            "建议运行 pipe 或调整 INTEL_SCORE_WINDOW_DAYS"
        )
        if settings.notify_webhook:
            from engine.output.notifier import notify_unscored_backlog
            notify_unscored_backlog(domain_name, unscored, settings.unscored_warn_threshold)
    except Exception as e:
        logger.warning(f"[{domain_name}] 待评分检查失败: {e}")


def _record_daily_snapshot(domain_name: str) -> None:
    """写入当日统计快照（采集/精选/分类分布）。"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        with Store() as store:
            fetched = store.conn.execute(
                "SELECT COUNT(*) as c FROM raw_items WHERE fetched_at LIKE ?",
                (f"{today}%",),
            ).fetchone()["c"]
            scored = store.conn.execute(
                "SELECT COUNT(*) as c FROM scored_items WHERE domain = ? AND created_at LIKE ?",
                (domain_name, f"{today}%"),
            ).fetchone()["c"]
            selected = store.conn.execute(
                "SELECT COUNT(*) as c FROM scored_items WHERE domain = ? AND created_at LIKE ? AND score >= 6.0",
                (domain_name, f"{today}%"),
            ).fetchone()["c"]
            cat_rows = store.conn.execute(
                """SELECT category, COUNT(*) as cnt FROM scored_items
                   WHERE domain = ? AND created_at LIKE ? AND score >= 6.0 AND category IS NOT NULL
                   GROUP BY category""",
                (domain_name, f"{today}%"),
            ).fetchall()
            categories = {r["category"]: r["cnt"] for r in cat_rows}
            store.save_daily_snapshot(
                domain_name, today,
                fetched=fetched, scored=scored, selected=selected,
                category_breakdown=categories,
            )
        logger.info(f"[{domain_name}] 日统计快照已更新: 采集 {fetched} / 评分 {scored} / 精选 {selected}")
    except Exception as e:
        logger.warning(f"[{domain_name}] 日统计快照失败: {e}")


def _record_pipe_run(domain_name: str, result: PipelineResult) -> None:
    """记录 pipe 运行结果，供 stats / 健康 Tab 使用。"""
    try:
        fr = result.fetch
        flt = result.filter
        error_sources = [e.source_id for e in fr.errors] if fr and fr.errors else []
        with Store() as store:
            store.save_pipe_run(
                domain=domain_name,
                duration_seconds=result.duration_seconds,
                fetch_new=len(fr.new_items) if fr else 0,
                fetch_errors=len(error_sources),
                fetch_error_sources=error_sources,
                scored=flt.scored_total if flt else 0,
                error=result.error,
            )
    except Exception as e:
        logger.warning(f"[{domain_name}] pipe 运行记录失败: {e}")
