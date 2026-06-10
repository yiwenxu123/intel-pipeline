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
from engine.filter.pipeline import pre_filter, pre_filter_with_rules, score_items
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
        return result

    # ── 2. 筛选 ──
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
                    RawItem(source_id=r["source_id"], title=r["title"], url=r["url"],
                            content=r["content"] or "", lang=r["lang"] or "zh")
                    for r in rows
                ]
                # 前置过滤：基于规则排除低质量、无关的信息
                items = pre_filter_with_rules(items, domain)
                filtered = pre_filter(items, domain)
                scored = score_items(filtered, domain)
                for si in scored:
                    raw_id = store.save_raw(si.raw)
                    store.save_scored(raw_id, domain.name, si)
                result.filter = FilterResult(
                    scored_items=scored, pre_filter_total=len(items),
                    pre_filter_passed=len(filtered), scored_total=len(scored),
                )
                logger.info(f"[{domain.name}] 筛选完成: {len(scored)}/{len(items)} 条")
            else:
                logger.info(f"[{domain.name}] 无待筛选条目")
    except Exception as e:
        logger.error(f"[{domain.name}] 筛选阶段失败: {e}")
        result.error = f"筛选失败: {e}"
        result.duration_seconds = time.time() - start
        return result

    # ── 3. 日报 ──
    try:
        from engine.output.report import generate_report, save_report
        with Store() as store:
            rows = store.get_selected(domain.name, take=100, min_score=6.0)
            if rows:
                items = []
                for r in rows:
                    raw = RawItem(source_id=r["source_id"], title=r["title"],
                                  url=r["url"], content=r.get("content", ""))
                    items.append(ScoredItem(
                        raw=raw, score=r["score"], category=r.get("category", ""),
                        summary=r.get("summary", ""), reason=r.get("reason", ""),
                    ))
                stats = store.get_stats(domain.name)
                report = generate_report(items, domain, total_fetched=stats.get("total_fetched", 0))
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
                notify_report(domain.name, stats, selected)
                result.notified = True
                logger.info(f"[{domain.name}] 推送通知已发送")
        except Exception as e:
            logger.error(f"[{domain.name}] 推送通知失败: {e}")

    result.duration_seconds = round(time.time() - start, 2)
    return result
