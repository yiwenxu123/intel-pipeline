"""关键词自动验证：暂存 → 试验 → 对比 → 合并/回滚。

实现 AutoResearch 的"试验-验证"模式：
1. evolve keywords 产出建议 → 写入暂存区
2. 下次 fetch 时，同时用正式关键词和暂存关键词采集
3. 对比两组的预筛通过率
4. 暂存组通过率更高 → 自动合并到 keywords.yaml
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from engine.config import settings
from engine.store import Store

logger = logging.getLogger(__name__)

# 暂存区路径
STAGING_FILE = "data/keyword_staging.json"


def _staging_path(domain: str) -> Path:
    return settings.project_root / "data" / f"keyword_staging_{domain}.json"


def stage_suggestions(domain: str, keywords: list[str]) -> dict:
    """将建议关键词写入暂存区。"""
    path = _staging_path(domain)
    staging = {
        "domain": domain,
        "staged_at": datetime.now().isoformat(),
        "keywords": keywords,
        "status": "pending",  # pending / accepted / rejected
        "trial_results": None,
    }
    path.write_text(json.dumps(staging, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"[{domain}] {len(keywords)} 个关键词已暂存: {path}")
    return staging


def get_staging(domain: str) -> Optional[dict]:
    """读取暂存区。"""
    path = _staging_path(domain)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def get_staged_keywords(domain: str) -> list[str]:
    """获取暂存中的关键词列表（仅 pending 状态）。"""
    staging = get_staging(domain)
    if staging and staging.get("status") == "pending":
        return staging.get("keywords", [])
    return []


def record_trial_result(domain: str, staged_pass_rate: float, official_pass_rate: float):
    """记录试验结果。"""
    path = _staging_path(domain)
    if not path.exists():
        return
    staging = json.loads(path.read_text(encoding="utf-8"))
    staging["trial_results"] = {
        "staged_pass_rate": round(staged_pass_rate, 4),
        "official_pass_rate": round(official_pass_rate, 4),
        "improvement": round(staged_pass_rate - official_pass_rate, 4),
        "tested_at": datetime.now().isoformat(),
    }
    # 自动决策
    if staged_pass_rate > official_pass_rate:
        staging["status"] = "accepted"
        logger.info(f"[{domain}] 暂存关键词验证通过：通过率提升 {staged_pass_rate - official_pass_rate:.1%}")
    else:
        staging["status"] = "rejected"
        logger.info(f"[{domain}] 暂存关键词验证未通过：通过率无提升")
    path.write_text(json.dumps(staging, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_staged_keywords(domain: str) -> bool:
    """将验证通过的暂存关键词合并到 keywords.yaml。返回是否成功。"""
    staging = get_staging(domain)
    if not staging or staging.get("status") != "accepted":
        return False

    keywords_path = settings.project_root / "domains" / domain / "keywords.yaml"
    if not keywords_path.exists():
        return False

    keywords = staging.get("keywords", [])
    if not keywords:
        return False

    # 读取现有关键词，去重
    import yaml
    with open(keywords_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    existing = set(data.get("keywords", []))
    new_keywords = [kw for kw in keywords if kw not in existing]

    if not new_keywords:
        logger.info(f"[{domain}] 暂存关键词已全部存在，跳过合并")
        _clear_staging(domain)
        return True

    # 追加到 YAML
    date = datetime.now().strftime("%Y-%m-%d")
    with open(keywords_path, "a", encoding="utf-8") as f:
        f.write(f"\n  # auto-validated on {date}\n")
        for kw in new_keywords:
            f.write(f"  - {kw}\n")

    logger.info(f"[{domain}] 已合并 {len(new_keywords)} 个验证通过的关键词")
    _clear_staging(domain)
    return True


def reject_staged_keywords(domain: str):
    """拒绝暂存关键词。"""
    path = _staging_path(domain)
    if path.exists():
        staging = json.loads(path.read_text(encoding="utf-8"))
        staging["status"] = "rejected"
        path.write_text(json.dumps(staging, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"[{domain}] 暂存关键词已拒绝")


def _clear_staging(domain: str):
    """清除暂存区。"""
    path = _staging_path(domain)
    if path.exists():
        path.unlink()


def check_and_apply(domain: str) -> dict:
    """检查暂存区状态，如果有验证通过的关键词则自动合并。

    在管道执行后调用。
    """
    staging = get_staging(domain)
    if not staging:
        return {"action": "none"}

    status = staging.get("status")
    if status == "accepted":
        applied = apply_staged_keywords(domain)
        return {"action": "applied", "keywords": staging.get("keywords", []), "success": applied}
    elif status == "rejected":
        _clear_staging(domain)
        return {"action": "rejected"}
    else:
        return {"action": "pending"}
