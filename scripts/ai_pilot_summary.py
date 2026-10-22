"""W3-03 AI 试点每日摘要：从腾讯云 Hermes 容器读取 xiaobai 当日 signals/topics。

用法：
  .venv/bin/python scripts/ai_pilot_summary.py --date 20261023
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

REMOTE_SCRIPT = r'''
import collections, glob, json, os, sys
base = {base!r}
date = {date!r}
signals_path = os.path.join(base, f"xiaobai_{date}_signals.json")
topics_path = os.path.join(base, f"xiaobai_{date}_topics.json")
if not os.path.exists(signals_path):
    print(json.dumps({{"error": f"signals not found: {{signals_path}}"}}, ensure_ascii=False))
    sys.exit(0)
data = json.load(open(signals_path, encoding="utf-8"))
signals = data.get("signals", [])
topics = []
if os.path.exists(topics_path):
    t = json.load(open(topics_path, encoding="utf-8"))
    topics = t.get("curated_topics") or t.get("topics") or []
print(json.dumps({{
    "date": date,
    "raw": data.get("raw_signals_count", 0),
    "filtered": data.get("filtered_signals_count", 0),
    "top": len(signals),
    "aihot_top20": sum(1 for s in signals if s.get("source") == "aihot"),
    "sources": dict(collections.Counter(s.get("source") for s in signals)),
    "quality": data.get("quality_score"),
    "topics": len(topics),
}}, ensure_ascii=False))
'''


def main() -> None:
    parser = argparse.ArgumentParser(description="W3-03 AI 试点每日摘要")
    parser.add_argument("--date", default=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"))
    parser.add_argument("--host", default="my-server")
    parser.add_argument("--container", default="hermes-agent")
    parser.add_argument("--base", default="/opt/data/skills/content-theme-finder/data")
    args = parser.parse_args()

    remote = REMOTE_SCRIPT.format(base=args.base, date=args.date)
    cmd = [
        "ssh", "-o", "ConnectTimeout=15", "-o", "BatchMode=yes", args.host,
        f"docker exec -i {args.container} python3 -",
    ]
    result = subprocess.run(cmd, input=remote, capture_output=True, text=True, timeout=45)
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit(result.returncode)
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        print(result.stdout, file=sys.stderr)
        raise SystemExit(1)
    if data.get("error"):
        print(data["error"], file=sys.stderr)
        raise SystemExit(1)

    print(
        f"{data['date']} | raw={data['raw']} filtered={data['filtered']} top={data['top']} "
        f"aihot_top20={data['aihot_top20']} topics={data['topics']} quality={data.get('quality')}"
    )
    print("sources=" + json.dumps(data.get("sources", {}), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
