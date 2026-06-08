"""CLI 入口：用 click 构建命令行工具。"""

from __future__ import annotations

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


@cli.command()
@click.option("--max-workers", default=4, help="并发采集数")
def fetch(max_workers: int):
    """采集：拉取所有信源，去重后存入数据库（无时间过滤）。"""
    from engine.domain import load_domain
    from engine.fetcher.runner import fetch_all
    from engine.store import Store

    domain = load_domain()
    store = Store()
    items = fetch_all(domain, store, max_workers=max_workers)
    store.close()

    console.print(f"\n✅ 采集完成：新增 [bold green]{len(items)}[/] 条")
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
    """筛选：对最近 3 天的未评分条目做 LLM 筛选（边评边存）。"""
    from datetime import datetime, timedelta, timezone
    from engine.config import settings
    from engine.domain import load_domain
    from engine.filter.pipeline import pre_filter, score_items
    from engine.models import RawItem
    from engine.store import Store

    domain = load_domain()
    store = Store()

    # 只处理最近 N 天内未评分的条目
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
        store.close()
        return

    items = [
        RawItem(
            source_id=r["source_id"],
            title=r["title"],
            url=r["url"],
            content=r["content"] or "",
            lang=r["lang"] or "zh",
        )
        for r in rows
    ]

    console.print(f"最近 {settings.score_window_days} 天待筛选：{len(items)} 条")

    # 预筛
    filtered = pre_filter(items, domain)
    console.print(f"预筛通过 {len(filtered)} 条，开始逐批评分...")

    # 批量评分，每批立即写入
    total_saved = 0
    batch_size = 5
    for i in range(0, len(filtered), batch_size):
        batch = filtered[i : i + batch_size]
        scored_batch = score_items(batch, domain, batch_size=batch_size)
        for si in scored_batch:
            raw_id = store.save_raw(si.raw)
            store.save_scored(raw_id, domain.name, si)
        total_saved += len(scored_batch)
        console.print(f"  进度：{total_saved}/{len(filtered)} 条已写入")

    selected = store.get_selected(domain.name, take=20, min_score=6.0)
    store.close()

    console.print(f"\n✅ 筛选完成：{total_saved} 条评分并入库，精选 {len(selected)} 条")

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
                (item.get('reason') or '')[:40],
            )
        console.print(table)


@cli.command()
def report():
    """日报：生成今日情报简报（Markdown + JSON）。"""
    from engine.domain import load_domain
    from engine.models import ScoredItem
    from engine.output.report import generate_report, save_report
    from engine.store import Store

    domain = load_domain()
    store = Store()

    rows = store.get_selected(domain.name, take=100, min_score=6.0)
    if not rows:
        console.print("⚠️  没有精选条目，请先运行 [bold]intel fetch[/] 和 [bold]intel filter[/]")
        store.close()
        return

    # 转为 ScoredItem（简化版，从数据库重建）
    items = []
    for r in rows:
        from engine.models import RawItem
        raw = RawItem(
            source_id=r["source_id"],
            title=r["title"],
            url=r["url"],
            content=r.get("content", ""),
        )
        items.append(ScoredItem(
            raw=raw,
            score=r["score"],
            category=r.get("category", ""),
            tags=[],
            summary=r.get("summary", ""),
            reason=r.get("reason", ""),
            entities=[],
        ))

    stats = store.get_stats(domain.name)
    report = generate_report(items, domain, total_fetched=stats.get("total_fetched", 0))
    md_path, json_path = save_report(report)
    store.close()

    console.print(f"\n✅ 日报已生成：")
    console.print(f"   📄 {md_path}")
    console.print(f"   📊 {json_path}")


@cli.command()
def api():
    """API：启动 REST API 服务。"""
    from engine.output.api import start_api
    console.print(f"🚀 启动 API 服务...")
    start_api()


@cli.command()
def pipe():
    """完整流水线：fetch → filter → report 一键执行。"""
    console.print("🔄 执行完整流水线...\n")
    ctx = click.get_current_context()
    ctx.invoke(fetch)
    ctx.invoke(filter)
    ctx.invoke(report)
    console.print("\n🎉 流水线执行完毕！")


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
    from engine.evolution.source_analyzer import save_source_report
    domain = settings.domain
    path = save_source_report(domain, days)
    console.print(f"✅ 信源质量报告已生成: {path}")


@evolve.command(name="scoring")
@click.option("--days", default=7, help="分析天数")
def evolve_scoring(days: int):
    """评分分析。"""
    from engine.config import settings
    from engine.evolution.scoring_calibrator import save_scoring_report
    domain = settings.domain
    path = save_scoring_report(domain, days)
    console.print(f"✅ 评分分析报告已生成: {path}")


@evolve.command()
@click.option("--days", default=7, help="分析天数")
def keywords(days: int):
    """关键词扩展分析。"""
    from engine.config import settings
    from engine.evolution.keyword_expander import save_keyword_report
    domain = settings.domain
    path = save_keyword_report(domain, days)
    console.print(f"✅ 关键词分析报告已生成: {path}")


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

    console.print(f"\n🎉 进化分析完成！")


if __name__ == "__main__":
    cli()
