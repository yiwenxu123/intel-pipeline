"""离线金标评测：对 frozen gold 跑规则预筛 + LLM 评分 + 质量闸门。

用法：
  .venv/bin/python scripts/eval_gold.py --baseline
  .venv/bin/python scripts/eval_gold.py --prompt domains/elderly-care/scoring_v2.md --limit 5
  .venv/bin/python scripts/eval_gold.py --prompt domains/elderly-care/scoring_v2.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from engine.config import settings
from engine.filter.pipeline import score_items
from engine.filter.quality_gates import apply_quality_gates
from engine.filter.rule_prefilter import rule_prefilter_items
from engine.models import RawItem

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = PROJECT_ROOT / "data" / "gold" / "elderly-care-20261022-final-v2.jsonl"


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _raw(item: dict) -> RawItem:
    return RawItem(
        source_id=item.get("source_id") or "unknown",
        title=item.get("title") or item.get("title_original") or "",
        url=item.get("url") or "",
        content=item.get("content") or item.get("summary") or "",
        published=_parse_dt(item.get("published")),
        lang=item.get("language") or "zh",
    )


def _key(item: dict) -> str:
    return item.get("url") or item.get("title") or item.get("case_id") or ""


def _predict_baseline(rows: list[dict]) -> dict[str, dict]:
    pred = {}
    for row in rows:
        score = float(row.get("score") or 0)
        category = row.get("category") or ""
        pred[_key(row)] = {
            "score": score,
            "category": category,
            "selected": score >= 5.5 and category != "rejected",
            "content_type": row.get("content_type") or "news",
            "reason": row.get("reason") or "",
        }
    return pred


def _predict_llm(rows: list[dict], prompt: str, domain: str,
                 sleep_seconds: float = 2.5) -> dict[str, dict]:
    raws = [_raw(row) for row in rows]
    passed, rejected = rule_prefilter_items(raws)
    pred: dict[str, dict] = {}
    for scored in rejected:
        pred[_key({"url": scored.raw.url, "title": scored.raw.title})] = {
            "score": float(scored.score),
            "category": scored.category,
            "selected": False,
            "content_type": scored.content_type,
            "reason": scored.reason,
        }

    domain_obj = SimpleNamespace(name=domain, scoring_prompt=prompt)
    for index, raw in enumerate(passed):
        scored = score_items([raw], domain_obj, batch_size=1, parallel=False)
        scored = [apply_quality_gates(item) for item in scored]
        for item in scored:
            pred[_key({"url": item.raw.url, "title": item.raw.title})] = {
                "score": float(item.score),
                "category": item.category,
                "selected": item.score >= 5.5 and item.category != "rejected",
                "content_type": item.content_type,
                "reason": item.reason,
            }
        if sleep_seconds and index < len(passed) - 1:
            time.sleep(sleep_seconds)
    return pred


def _metrics(rows: list[dict], pred: dict[str, dict]) -> dict:
    labels = []
    for row in rows:
        decision = (row.get("gold") or {}).get("decision")
        if decision not in ("select", "reject"):
            continue
        p = pred.get(_key(row))
        if not p:
            continue
        labels.append((decision, bool(p["selected"])))
    tp = sum(1 for gold, selected in labels if gold == "select" and selected)
    fp = sum(1 for gold, selected in labels if gold == "reject" and selected)
    fn = sum(1 for gold, selected in labels if gold == "select" and not selected)
    tn = sum(1 for gold, selected in labels if gold == "reject" and not selected)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    top20 = sorted(rows, key=lambda row: pred.get(_key(row), {}).get("score", -1), reverse=True)[:20]
    top20_select = sum(1 for row in top20 if (row.get("gold") or {}).get("decision") == "select")
    return {
        "n": len(labels),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "top20_select": top20_select,
        "top20_precision": round(top20_select / max(len(top20), 1), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="离线金标评测")
    parser.add_argument("--gold", default=str(DEFAULT_GOLD))
    parser.add_argument("--prompt", default=str(PROJECT_ROOT / "domains" / "elderly-care" / "scoring.md"))
    parser.add_argument("--domain", default="elderly-care")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0 = 全部）")
    parser.add_argument("--baseline", action="store_true", help="不调 LLM，直接用 gold 里的 score 计算基线")
    parser.add_argument("--sleep", type=float, default=2.5, help="逐条评分间隔秒数（默认 2.5，避免 RPM 限流）")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    gold_path = Path(args.gold)
    rows = _load(gold_path)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("gold 为空")

    if args.baseline:
        pred = _predict_baseline(rows)
        label = "baseline"
    else:
        prompt = Path(args.prompt).read_text(encoding="utf-8")
        pred = _predict_llm(rows, prompt, args.domain, sleep_seconds=args.sleep)
        label = Path(args.prompt).stem

    missing = [row["case_id"] for row in rows if _key(row) not in pred]
    metrics = _metrics(rows, pred)
    print(f"gold={gold_path} n={len(rows)} mode={label} model={settings.llm_scoring_model}")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if missing:
        print(f"WARNING missing predictions: {len(missing)}", file=sys.stderr)
        print(missing[:10], file=sys.stderr)

    output = Path(args.output) if args.output else (PROJECT_ROOT / "data" / "gold" / f"eval-{label}.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            p = pred.get(_key(row), {})
            payload = {
                "case_id": row.get("case_id"),
                "title": row.get("title"),
                "gold": (row.get("gold") or {}).get("decision"),
                "pred_score": p.get("score"),
                "pred_category": p.get("category"),
                "pred_selected": p.get("selected"),
                "pred_content_type": p.get("content_type"),
                "pred_reason": p.get("reason"),
            }
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(f"predictions -> {output}")


if __name__ == "__main__":
    main()
