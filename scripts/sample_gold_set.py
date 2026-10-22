"""从生产库抽取养老金标样本，输出可人工标注的 JSONL。

用法（Windows）：
  .venv\\Scripts\\python.exe scripts\\sample_gold_set.py --limit 100 --days 30

用法（macOS）：
  .venv/bin/python scripts/sample_gold_set.py --db data/intel-elderly-care.db \
    --limit 100 --days 10000 --output /tmp/gold.jsonl

标注：把每行 gold.decision 填成 select / reject / either；notes 写理由。
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _load_rows(db_path: Path, domain: str, days: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT s.id, s.score, s.category, s.summary, s.reason,
                      s.headline, s.lead, s.takeaway, s.key_points,
                      s.tags, s.entities, s.content_type,
                      r.title, r.url, r.content, r.full_text, r.published,
                      r.source_id, r.lang
               FROM scored_items s
               JOIN raw_items r ON s.raw_id = r.id
               WHERE s.domain = ? AND s.created_at >= ?
               ORDER BY s.score DESC""",
            (domain, cutoff),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _sample(rows: list[dict], limit: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    positives = [r for r in rows if r["score"] >= 5.5 and r["category"] != "rejected"]
    negatives = [r for r in rows if r["score"] < 5.5 or r["category"] == "rejected"]
    hard = [r for r in rows if 4.5 <= float(r["score"] or 0) < 6.5]
    rng.shuffle(positives)
    rng.shuffle(negatives)
    rng.shuffle(hard)

    picked: list[dict] = []
    used: set[int] = set()

    def take(pool: list[dict], n: int) -> None:
        for row in pool:
            if len(picked) >= limit or n <= 0:
                return
            if row["id"] in used:
                continue
            picked.append(row)
            used.add(row["id"])
            n -= 1

    hard_target = min(limit // 5, len(hard))
    take(hard, hard_target)
    remaining = limit - len(picked)
    take(positives, remaining // 2)
    take(negatives, limit - len(picked))
    take(positives + negatives + hard, limit - len(picked))
    return picked


def _to_record(row: dict, domain: str, index: int) -> dict:
    score = float(row["score"] or 0)
    if 4.5 <= score < 6.5:
        group = "hard"
    elif score >= 5.5 and row["category"] != "rejected":
        group = "positive"
    else:
        group = "negative"
    title_zh = (row.get("headline") or "").strip()
    title_original = (row.get("title") or "").strip()
    content = row.get("full_text") or row.get("content") or ""
    return {
        "case_id": f"{domain}-{index:04d}",
        "domain": domain,
        "sample_group": group,
        "title": title_zh or title_original,
        "title_original": title_original,
        "summary": row.get("summary") or row.get("lead") or "",
        "content": content[:2000],
        "url": row.get("url") or "",
        "source_id": row.get("source_id") or "",
        "published": row.get("published") or "",
        "score": score,
        "category": row.get("category") or "",
        "content_type": row.get("content_type") or "news",
        "reason": row.get("reason") or "",
        "key_points": _load_json_list(row.get("key_points")),
        "tags": _load_json_list(row.get("tags")),
        "entities": _load_json_list(row.get("entities")),
        "gold": {"decision": "", "notes": ""},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="抽取养老金标样本")
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "intel-elderly-care.db"))
    parser.add_argument("--domain", default="elderly-care")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--exclude", default="", help="排除已有 gold 的 JSONL/URL 列表，避免 holdout 重叠")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "data" / "gold" / "elderly-care.jsonl"))
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在: {db_path}")
    rows = _load_rows(db_path, args.domain, args.days)
    if args.exclude:
        exclude_path = Path(args.exclude)
        excluded: set[str] = set()
        if exclude_path.exists():
            for line in exclude_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("{"):
                    try:
                        excluded.add(json.loads(line).get("url") or "")
                    except json.JSONDecodeError:
                        continue
                else:
                    excluded.add(line)
            rows = [row for row in rows if row.get("url") not in excluded]
        print(f"排除已有样本 URL：{len(excluded)} 个，剩余候选 {len(rows)} 条")
    if not rows:
        raise SystemExit(f"{args.domain} 最近 {args.days} 天没有已评分条目")
    picked = _sample(rows, args.limit, args.seed)
    records = [_to_record(row, args.domain, i + 1) for i, row in enumerate(picked)]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    counts = {"positive": 0, "negative": 0, "hard": 0}
    for record in records:
        counts[record["sample_group"]] += 1
    print(f"已抽取 {len(records)} 条 → {out_path}")
    print(f"分组：{counts}")
    print("下一步：逐行填写 gold.decision = select / reject / either，notes 写理由。")


if __name__ == "__main__":
    main()
