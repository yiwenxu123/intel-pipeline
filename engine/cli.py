"""CLI 入口：用 click 构建命令行工具。"""

from __future__ import annotations

import json
import logging
import sys

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="详细日志")
@click.option("-d", "--domain", default=None, help="领域名称（默认读配置）")
def cli(verbose: bool, domain: str | None):
    """Intel Pipeline — 可配置的行业情报引擎。"""
    _setup_logging(verbose)
    if domain:
        from engine.config import settings
        settings.domain = domain
        # 确保 db_path 与 domain 同步（model_post_init 只在初始化时调用一次）
        settings.db_path = f"data/intel-{domain}.db"


@cli.command()
@click.option("--max-workers", default=4, help="并发采集数")
def fetch(max_workers: int):
    """采集：拉取所有信源，去重后存入数据库（无时间过滤）。"""
    from engine.domain import load_domain
    from engine.fetcher.runner import fetch_all
    from engine.store import Store

    domain = load_domain()
    store = Store()
    result = fetch_all(domain, store, max_workers=max_workers)
    store.close()

    items = result.new_items
    console.print(f"\n✅ 采集完成：新增 [bold green]{len(items)}[/] 条 | "
                  f"信源 [bold]{result.sources_success}/{result.sources_total}[/] 成功 | "
                  f"耗时 {result.duration_seconds}s")

    if result.errors:
        console.print(f"\n⚠️  [bold yellow]{len(result.errors)}[/] 个信源采集失败：")
        err_table = Table(show_header=True)
        err_table.add_column("信源", style="red", width=20)
        err_table.add_column("错误类型", style="dim", width=12)
        err_table.add_column("错误信息")
        for err in result.errors:
            err_table.add_row(err.source_id, err.error_type, err.error[:80])
        console.print(err_table)

    if items:
        table = Table(title="最新采集（前 10 条）")
        table.add_column("来源", style="cyan", width=15)
        table.add_column("日期", style="dim", width=12)
        table.add_column("标题", style="white")
        for item in items[:10]:
            date = item.published.strftime("%m-%d") if item.published else "无日期"
            table.add_row(item.source_id, date, item.title[:55])
        console.print(table)


@cli.command()
def filter():
    """筛选：对窗口期内未评分条目做 LLM 筛选（边评边存），窗口天数由 INTEL_SCORE_WINDOW_DAYS 配置（默认 7）。"""
    import time
    from datetime import datetime, timedelta, timezone
    from engine.config import settings
    from engine.domain import load_domain
    from engine.filter.runner import filter_and_score
    from engine.models import RawItem
    from engine.store import Store

    domain = load_domain()
    filter_start = time.time()

    from engine.filter.llm_client import reset_usage
    reset_usage()

    with Store() as store:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.score_window_days)).isoformat()
        rows = store.conn.execute(
            """SELECT r.* FROM raw_items r
               WHERE r.published >= ?
               AND r.id NOT IN (SELECT raw_id FROM scored_items WHERE domain = ?)
               ORDER BY r.published DESC""",
            (cutoff, domain.name),
        ).fetchall()

        if not rows:
            console.print(f"✅ 最近 {settings.score_window_days} 天内没有待筛选的条目")
            return

        items = [
            RawItem(
                source_id=r["source_id"],
                title=r["title"],
                url=r["url"],
                content=r["content"] or "",
                lang=r["lang"] or "zh",
                full_text=r["full_text"],
            )
            for r in rows
        ]

        total_input = len(items)
        console.print(f"最近 {settings.score_window_days} 天待筛选：{total_input} 条")

        scored_batch, _ = filter_and_score(items, domain, store)
        for si in scored_batch:
            raw_id = store.save_raw(si.raw)
            store.save_scored(raw_id, domain.name, si)
        total_saved = len(scored_batch)
        console.print(f"  评分完成：{total_saved} 条已写入")

        selected = store.get_selected(domain.name, take=20, min_score=6.0)

        filter_duration = time.time() - filter_start
        from engine.filter.llm_client import get_usage
        usage = get_usage()

        try:
            store.save_llm_usage(
                domain.name, usage["calls"], usage["input_tokens"],
                usage["output_tokens"], filter_duration, total_saved,
            )
        except Exception:
            pass

    console.print(f"\n✅ 筛选完成：{total_saved} 条评分并入库，精选 {len(selected)} 条")
    console.print(f"   📊 统计：耗时 {filter_duration:.1f}s | LLM 调用 {usage['calls']} 次 | "
                  f"输入 {usage['input_tokens']} tokens | 输出 {usage['output_tokens']} tokens | "
                  f"精选率 {len(selected)/max(total_saved,1)*100:.0f}%")

    if selected:
        table = Table(title="精选条目（≥6.0 分）")
        table.add_column("分数", style="bold", width=6)
        table.add_column("分类", style="cyan", width=10)
        table.add_column("标题", style="white")
        table.add_column("理由", style="dim", max_width=40)
        for item in selected[:15]:
            table.add_row(
                f"{item['score']:.1f}",
                item.get('category', ''),
                item['title'][:50],
                (item.get('takeaway') or item.get('reason') or '')[:40],
            )
        console.print(table)


@cli.command()
@click.option("--date", default=None, help="日期 YYYY-MM-DD（默认昨日）")
def report(date: str | None):
    """日报：生成情报简报（Markdown + JSON），默认昨日。"""
    from datetime import datetime, timedelta, timezone
    from engine.domain import load_domain
    from engine.models import ScoredItem
    from engine.output.report import generate_report, save_report, compute_trend_text
    from engine.store import Store

    domain = load_domain()

    report_date = date or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    with Store() as store:
        rows = store.get_selected(domain.name, take=100, min_score=6.0, published_date=report_date)
        if not rows:
            console.print(f"⚠️  {report_date} 没有精选条目，请先运行 [bold]intel filter[/]")
            return

        items = []
        for r in rows:
            from engine.models import RawItem
            raw = RawItem(
                source_id=r["source_id"],
                title=r["title"],
                url=r["url"],
                content=r.get("content", ""),
                published=r.get("published"),
            )
            tags_val = json.loads(r.get("tags", "[]")) if isinstance(r.get("tags"), str) else (r.get("tags") or [])
            entities_val = json.loads(r.get("entities", "[]")) if isinstance(r.get("entities"), str) else (r.get("entities") or [])
            key_points_val = json.loads(r.get("key_points", "[]")) if isinstance(r.get("key_points"), str) else (r.get("key_points") or [])
            items.append(ScoredItem(
                raw=raw,
                score=r["score"],
                category=r.get("category", ""),
                tags=tags_val,
                summary=r.get("summary", ""),
                key_points=key_points_val,
                reason=r.get("reason", ""),
                entities=entities_val,
                title_display=r.get("title_display", "") or "",
                headline=r.get("headline", "") or "",
                lead=r.get("lead", "") or "",
                takeaway=r.get("takeaway", "") or "",
                insight_type=r.get("insight_type", "fact") or "fact",
                content_type=r.get("content_type", "news") or "news",
            ))

        stats = store.get_stats(domain.name)
        trend_text = compute_trend_text(store, domain.name)
        report = generate_report(
            items, domain, total_fetched=stats.get("total_fetched", 0),
            trend_text=trend_text, date=report_date,
        )
        md_path, json_path = save_report(report)

    console.print("\n✅ 日报已生成：")
    console.print(f"   📄 {md_path}")
    console.print(f"   📊 {json_path}")


@cli.command("quality-review")
@click.option("--take", default=20, help="抽样条数")
@click.option("--days", default=7, help="最近 N 天")
@click.option("--min-score", default=6.0, help="最低分数（无精选时可降到 4.0 审分布）")
@click.option("--output", default=None, help="输出 Markdown 路径（默认 data/reports/）")
def quality_review(take: int, days: int, min_score: float, output: str | None):
    """质量验收：导出近期精选条目供人工审阅（新领域上线 / 调 prompt 后用）。"""
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from engine.config import settings
    from engine.domain import load_domain
    from engine.store import Store

    domain = load_domain()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with Store() as store:
        rows = store.get_scored_for_review(
            domain.name, since=cutoff, take=take, min_score=min_score,
        )

    if not rows:
        console.print(f"⚠️  最近 {days} 天无 ≥{min_score} 分条目，请先运行 pipe 或降低 --min-score")
        return

    lines = [
        f"# {domain.name} 质量验收抽样",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 抽样范围：最近 {days} 天，Top {len(rows)} 条（≥{min_score} 分）",
        "- 验收标准：误报率 < 20%（与中非/领域主题无关、无具体事实视为误报）",
        "",
        "## 条目清单",
        "",
    ]
    for i, row in enumerate(rows, 1):
        lines.extend([
            f"### {i}. [{row.get('score', 0):.1f}] {row.get('title_display') or row.get('title', '')}",
            "",
            f"- **分类**：{row.get('category', '')}",
            f"- **信源**：{row.get('source_id', '')}",
            f"- **摘要**：{row.get('summary', '')}",
            f"- **理由**：{row.get('reason', '')}",
            f"- **链接**：{row.get('url', '')}",
            "- **验收**：[ ] 通过  [ ] 误报  [ ] 待观察",
            "",
        ])

    lines.extend([
        "## 验收结论",
        "",
        "- 误报数：__ / " + str(len(rows)),
        "- 是否调整 scoring.md：[ ] 是  [ ] 否",
        "- 备注：",
        "",
    ])

    content = "\n".join(lines)
    out_path = Path(output) if output else (
        settings.project_root / settings.report_dir / f"quality-{domain.name}-{datetime.now().strftime('%Y-%m-%d')}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")

    table = Table(title=f"质量验收抽样（{len(rows)} 条）")
    table.add_column("#", width=3)
    table.add_column("分", width=5)
    table.add_column("分类", width=12)
    table.add_column("标题")
    for i, row in enumerate(rows, 1):
        table.add_row(
            str(i),
            f"{row.get('score', 0):.1f}",
            row.get("category", ""),
            (row.get("title_display") or row.get("title", ""))[:50],
        )
    console.print(table)
    console.print(f"\n✅ 验收报告已保存：{out_path}")


@cli.command("quality-metrics")
def quality_metrics():
    """输出内部产品级 DoD 质量指标。"""
    from engine.domain import load_domain
    from engine.ops.quality_metrics import compute_quality_metrics, DOD_TARGETS
    from engine.store import Store

    domain = load_domain()
    with Store() as store:
        m = compute_quality_metrics(domain.name, store)

    metrics = m["metrics"]
    dod = m["dod"]
    table = Table(title=f"{domain.name} 质量指标（DoD）")
    table.add_column("指标", style="cyan")
    table.add_column("当前", justify="right")
    table.add_column("目标", justify="right")
    table.add_column("状态", justify="center")

    def _status(ok: bool | None) -> str:
        if ok is None:
            return "—"
        return "[green]✅[/]" if ok else "[red]❌[/]"

    table.add_row("待评分积压", str(metrics["unscored_count"]), f"< {DOD_TARGETS['unscored_count']}", _status(dod["D1_unscored_ok"]))
    table.add_row("简报覆盖率", f"{metrics['briefing_coverage_pct']}%", f"≥ {DOD_TARGETS['briefing_coverage_pct']}%", _status(dod["D2_briefing_ok"]))
    pipe = metrics["pipe_7d"]
    table.add_row("7日pipe成功率", f"{pipe['success_rate_pct']}% ({pipe['success_runs']}/{pipe['total_runs']})", f"≥ {DOD_TARGETS['pipe_success_rate_pct']}%", _status(dod["D4_pipe_ok"]))
    table.add_row("最近采集失败", str(metrics["last_fetch_errors"]), f"< {DOD_TARGETS['fetch_errors_per_run']}", _status(dod["D5_last_fetch_errors_ok"]))
    table.add_row("API Token", "已配置" if dod["D8_api_token"] else "未配置", "建议配置", _status(dod["D8_api_token"]))
    console.print(table)
    fb = metrics["feedback_7d"]
    console.print(f"\n精选 {metrics['selected_count']} | 简报 {metrics['briefing_with_headline']} | 规则拒绝 {metrics['rule_rejected_count']}")
    console.print(f"反馈 7天：{fb['total']} 次（👍 {fb['upvotes']} / 👎 {fb['downvotes']}）")


@cli.command("refetch-fulltext")
@click.option("--source", "source_id", default=None, help="信源 ID（如 ageclub_web）")
@click.option("--url-pattern", default=None, help="URL 包含的子串（如 ageclub.net）")
@click.option("--limit", default=200, help="最多处理条数")
@click.option("--workers", default=3, help="并发数")
def refetch_fulltext(source_id: str | None, url_pattern: str | None, limit: int, workers: int):
    """批量重抓原文全文（修复脏数据或站点适配更新后刷新）。"""
    from engine.ops.refetch_full_text import refetch_full_text

    stats = refetch_full_text(
        source_id=source_id,
        url_pattern=url_pattern,
        limit=limit,
        max_workers=workers,
    )
    cleared = stats.get("cleared", 0)
    console.print(
        f"✅ 全文重抓完成：{stats['ok']} 成功 / {cleared} 清除脏数据 / "
        f"{stats['skipped']} 跳过 / {stats['failed']} 失败（共 {stats['total']} 条）"
    )


@cli.command("briefing-backfill")
@click.option("--days", default=30, help="回溯天数")
@click.option("--limit", default=50, help="每批最多处理条数")
@click.option("--dry-run", is_flag=True, help="仅统计待补全条数")
def briefing_backfill(days: int, limit: int, dry_run: bool):
    """为历史精选条目补全简报字段（headline/lead/takeaway）。"""
    from engine.domain import load_domain
    from engine.ops.briefing_backfill import backfill_briefings, count_needing_briefing
    from engine.store import Store

    domain = load_domain()
    with Store() as store:
        pending = count_needing_briefing(store, domain.name, days=days)
        if dry_run:
            console.print(f"待补全简报：{pending} 条（最近 {days} 天精选）")
            return
        result = backfill_briefings(domain, store, days=days, limit=limit, dry_run=False)
    console.print(f"✅ 简报补全：更新 {result['updated']}/{result['pending']} 条")
    if pending > result["updated"]:
        console.print(f"   仍有 {pending - result['updated']} 条待处理，可再次运行或提高 --limit")


@cli.command()
def preflight():
    """启动前检查：LLM 等必要配置。"""
    from engine.ops.preflight import run_preflight

    ok, errors = run_preflight()
    if ok:
        console.print("[green]✅ 配置检查通过[/]")
        return
    console.print("[red]❌ 配置检查失败：[/]")
    for e in errors:
        console.print(f"  • {e}")
    sys.exit(1)


@cli.group()
def ops():
    """运营工具：周报、积压消化等。"""


@ops.command("weekly-report")
@click.option("--notify", is_flag=True, help="推送飞书周报")
def ops_weekly_report(notify: bool):
    """生成运营周报（Markdown）。"""
    from engine.config import settings
    from engine.ops.weekly_report import notify_weekly_report, save_weekly_report

    path, _ = save_weekly_report(settings.domain)
    console.print(f"✅ 周报已保存：{path}")
    if notify:
        if notify_weekly_report(settings.domain):
            console.print("✅ 已推送飞书")
        else:
            console.print("⚠️  未配置 INTEL_NOTIFY_WEBHOOK，跳过推送")


@ops.command("digest-backlog")
@click.option("--target", default=50, help="目标待评分数")
@click.option("--max-runs", default=10, help="最多运行 pipe 次数")
def ops_digest_backlog(target: int, max_runs: int):
    """循环运行 pipe 直至待评分低于目标。"""
    from engine.domain import load_domain
    from engine.pipeline import run_full_pipeline
    from engine.store import Store

    domain = load_domain()
    for i in range(max_runs):
        with Store() as store:
            n = store.get_unscored_count(domain.name)
        console.print(f"[{i + 1}/{max_runs}] 待评分 {n} 条")
        if n < target:
            console.print(f"✅ 积压已低于 {target}")
            return
        result = run_full_pipeline(domain, notify=False)
        if result.error:
            console.print(f"[red]pipe 失败：{result.error}[/]")
            sys.exit(1)
    console.print(f"[yellow]已达最大运行次数 {max_runs}，请稍后继续[/]")


@cli.command()
def api():
    """API：启动 REST API 服务。"""
    from engine.output.api import start_api
    console.print("🚀 启动 API 服务...")
    start_api()


@cli.command()
def pipe():
    """完整流水线：fetch → filter → report → notify 一键执行。"""
    from engine.domain import load_domain
    from engine.ops.preflight import run_preflight
    from engine.pipeline import run_full_pipeline

    ok, errors = run_preflight()
    if not ok:
        console.print("[red]❌ 配置检查失败，请先修复：[/]")
        for e in errors:
            console.print(f"  • {e}")
        sys.exit(1)

    domain = load_domain()
    console.print(f"🔄 执行 [{domain.name}] 完整流水线...\n")

    result = run_full_pipeline(domain)

    if result.error:
        console.print(f"❌ 管道失败: {result.error}")
        return

    # 采集结果
    if result.fetch:
        fr = result.fetch
        console.print(f"✅ 采集: 新增 {len(fr.new_items)} 条 | "
                      f"信源 {fr.sources_success}/{fr.sources_total} | "
                      f"耗时 {fr.duration_seconds}s")
        if fr.errors:
            for err in fr.errors:
                console.print(f"   ⚠️  {err.source_id}: {err.error}")

    # 筛选结果
    if result.filter:
        flt = result.filter
        pre_info = ""
        if flt.pre_filter_skipped:
            pre_info = f" | 规则过滤 {flt.pre_filter_skipped} 条"
        parse_info = ""
        if flt.json_parse_failures or flt.retry_success:
            parse_info = (
                f" | 解析失败 {flt.json_parse_failures} 条"
                f" | 重试成功 {flt.retry_success} 条"
            )
        console.print(
            f"✅ 筛选: {flt.scored_total} 条评分"
            f"{pre_info}{parse_info} | 耗时 {result.duration_seconds:.1f}s"
        )

    # 日报
    if result.report_path:
        console.print(f"✅ 日报: {result.report_path}")

    # 推送
    if result.notified:
        console.print("✅ 推送: 已发送")

    console.print(f"\n🎉 流水线执行完毕！总耗时 {result.duration_seconds}s")


# ── 自动进化命令组 ──

@cli.group()
def evolve():
    """自动进化：信源质量分析、评分校准、关键词扩展。"""
    pass


@evolve.command()
@click.option("--days", default=7, help="分析天数")
def sources(days: int):
    """信源质量分析。"""
    from engine.config import settings
    from engine.evolution.source_analyzer import save_source_report, analyze_source_quality
    domain = settings.domain
    path = save_source_report(domain, days)
    console.print(f"✅ 信源质量报告已生成: {path}")

    data = analyze_source_quality(domain, days)
    unhealthy = [s for s in data["sources"] if s["status"] in ("ineffective", "dormant")]
    if unhealthy:
        console.print(f"\n⚠️  {len(unhealthy)} 个信源连续 {days} 天无有效产出，建议检查：")
        for s in unhealthy:
            console.print(f"  - [bold]{s['source_id']}[/] ({s['status']}): 采集 {s['total']} 条，精选 0 条")


@evolve.command(name="scoring")
@click.option("--days", default=7, help="分析天数")
def evolve_scoring(days: int):
    """评分分析。"""
    from engine.config import settings
    from engine.evolution.scoring_calibrator import save_scoring_report, suggest_adjustments
    domain = settings.domain
    path = save_scoring_report(domain, days)
    console.print(f"✅ 评分分析报告已生成: {path}")

    suggestions = suggest_adjustments(domain, days)
    if suggestions:
        console.print("\n📋 调整建议：")
        for s in suggestions:
            console.print(f"  • {s}")


@evolve.command()
@click.option("--days", default=7, help="分析天数")
@click.option("--apply", "do_apply", is_flag=True, help="直接追加到 keywords.yaml（跳过验证）")
@click.option("--stage", is_flag=True, default=True, help="暂存建议供下次管道自动验证（默认）")
def keywords(days: int, do_apply: bool, stage: bool):
    """关键词扩展分析。默认暂存建议，下次管道自动验证效果。"""
    from engine.config import settings
    from engine.evolution.keyword_expander import save_keyword_report, suggest_new_keywords, suggest_keywords_yaml
    domain = settings.domain
    path = save_keyword_report(domain, days)
    console.print(f"✅ 关键词分析报告已生成: {path}")

    suggestions = suggest_new_keywords(domain, days)
    if suggestions:
        console.print(f"\n📋 建议新增 {len(suggestions)} 个关键词：")
        for kw in suggestions:
            console.print(f"  - {kw}")

        if do_apply:
            # 直接应用模式
            yaml_text = suggest_keywords_yaml(domain, days)
            if yaml_text:
                kw_path = settings.project_root / "domains" / domain / "keywords.yaml"
                console.print(f"\n将追加到 {kw_path}：")
                console.print(yaml_text)
                if click.confirm("确认追加？"):
                    with open(kw_path, "a", encoding="utf-8") as f:
                        f.write("\n" + yaml_text + "\n")
                    console.print(f"✅ 已追加到 {kw_path}")
                else:
                    console.print("已取消")
        elif stage:
            # 暂存验证模式（默认）
            from engine.evolution.keyword_staging import stage_suggestions
            stage_suggestions(domain, suggestions)
            console.print(f"\n📦 {len(suggestions)} 个关键词已暂存，下次管道执行时自动验证效果")
            console.print("   验证逻辑：暂存关键词参与采集过滤 → 对比通过率 → 自动合并或回滚")
    else:
        console.print("✅ 未发现新的关键词建议")


@evolve.command(name="all")
@click.option("--days", default=7, help="分析天数")
def evolve_all(days: int):
    """运行所有进化分析。"""
    from engine.config import settings
    from engine.evolution.source_analyzer import save_source_report
    from engine.evolution.scoring_calibrator import save_scoring_report
    from engine.evolution.keyword_expander import save_keyword_report

    domain = settings.domain
    console.print(f"🔄 运行 {domain} 领域的进化分析...")

    path1 = save_source_report(domain, days)
    console.print(f"  ✅ 信源质量: {path1}")

    path2 = save_scoring_report(domain, days)
    console.print(f"  ✅ 评分分析: {path2}")

    path3 = save_keyword_report(domain, days)
    console.print(f"  ✅ 关键词分析: {path3}")

    console.print("\n🎉 进化分析完成！")


@evolve.command()
def lifecycle():
    """查看信源生命周期状态（产出率追踪 + 降级记录）。"""
    from engine.config import settings
    from engine.evolution.source_lifecycle import get_lifecycle_status
    domain = settings.domain

    statuses = get_lifecycle_status(domain)
    if not statuses:
        console.print(f"暂无 {domain} 的信源度量数据。运行 pipe 后自动生成。")
        return

    table = Table(title=f"{domain} 信源生命周期")
    table.add_column("信源", style="cyan", width=20)
    table.add_column("状态", width=10)
    table.add_column("跟踪天数", justify="right", width=8)
    table.add_column("总采集", justify="right", width=8)
    table.add_column("总精选", justify="right", width=8)
    table.add_column("平均产出率", justify="right", width=10)
    table.add_column("最近日期", width=12)

    status_style = {
        "excellent": "[bold green]优秀[/]",
        "healthy": "[green]健康[/]",
        "low": "[yellow]低效[/]",
        "critical": "[red]危险[/]",
    }

    for s in statuses:
        table.add_row(
            s["source_id"],
            status_style.get(s["status"], s["status"]),
            str(s["days_tracked"]),
            str(s["total_fetched"]),
            str(s["total_selected"]),
            f"{s['avg_yield']*100:.1f}%",
            s["last_date"] or "",
        )
    console.print(table)


@evolve.command()
@click.argument("source_id")
def restore(source_id):
    """恢复被自动降级的信源。"""
    from engine.config import settings
    from engine.evolution.source_lifecycle import restore_source
    domain = settings.domain

    if restore_source(domain, source_id):
        console.print(f"✅ 信源 {source_id} 已恢复，下次采集将重新启用")
    else:
        console.print(f"⚠️  信源 {source_id} 未找到或不是自动降级的")


if __name__ == "__main__":
    cli()
