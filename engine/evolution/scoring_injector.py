"""评分校准注入：检测异常 → 生成校准指令 → 注入评分 prompt。

实现 AutoResearch 的"反馈驱动迭代"模式：
1. 分析评分分布，检测异常（某分类平均分过高/过低）
2. 生成针对性的校准指令
3. 下次评分时注入 system prompt
4. 跟踪校准前后的分布变化
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

# 异常阈值
HIGH_SCORE_THRESHOLD = 8.5      # 平均分 > 8.5 视为评分过松
LOW_SCORE_THRESHOLD = 4.0       # 平均分 < 4.0 视为评分过严
MIN_ITEMS_FOR_CALIBRATION = 3   # 至少 3 条才触发校准

# 校准指令存储
CALIBRATION_FILE = "data/scoring_calibration_{domain}.json"


def _calibration_path(domain: str) -> Path:
    return settings.project_root / "data" / f"scoring_calibration_{domain}.json"


def analyze_and_calibrate(domain: str, days: int = 7) -> dict:
    """分析评分分布，生成校准指令。"""
    from engine.evolution.scoring_calibrator import analyze_scoring_distribution
    data = analyze_scoring_distribution(domain, days)
    calibrations = []

    # 检查分类异常
    for cat in data.get("by_category", []):
        if cat["total"] < MIN_ITEMS_FOR_CALIBRATION:
            continue
        cat_id = cat["category"]
        avg = cat["avg_score"]

        if avg > HIGH_SCORE_THRESHOLD:
            calibrations.append({
                "type": "category_high",
                "target": cat_id,
                "avg_score": avg,
                "instruction": f"分类 '{cat_id}' 近期平均分 {avg:.1f}（偏高）。请严格评分：7分以上必须有具体数据支撑（金额、用户数、时间节点），泛泛而谈的内容不超过6分。",
            })
        elif avg < LOW_SCORE_THRESHOLD:
            calibrations.append({
                "type": "category_low",
                "target": cat_id,
                "avg_score": avg,
                "instruction": f"分类 '{cat_id}' 近期平均分 {avg:.1f}（偏低）。请检查是否过度严格：如果内容有明确事实和行业价值，可以给到6-7分。",
            })

    # 检查整体分布
    overall = data.get("overall", {})
    if overall.get("total", 0) >= 10:
        select_rate = overall.get("select_rate", 0)
        if select_rate > 80:
            calibrations.append({
                "type": "global_high",
                "target": "all",
                "avg_score": overall.get("avg_score", 0),
                "instruction": f"整体精选率 {select_rate:.0f}%（过高）。请提高标准：只有对从业者有直接决策价值的内容才给7分以上。",
            })
        elif select_rate < 10:
            calibrations.append({
                "type": "global_low",
                "target": "all",
                "avg_score": overall.get("avg_score", 0),
                "instruction": f"整体精选率 {select_rate:.0f}%（过低）。请检查是否过度严格：有明确事实的行业动态可以给到6分。",
            })

    result = {
        "domain": domain,
        "analyzed_at": datetime.now().isoformat(),
        "days": days,
        "calibrations": calibrations,
        "overall": overall,
    }

    # 保存校准指令
    if calibrations:
        path = _calibration_path(domain)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[{domain}] 生成 {len(calibrations)} 条评分校准指令")
    else:
        # 无异常，清除旧的校准指令
        path = _calibration_path(domain)
        if path.exists():
            path.unlink()
        logger.info(f"[{domain}] 评分分布正常，无需校准")

    return result


def get_calibration_instructions(domain: str) -> str:
    """获取当前有效的校准指令，注入评分 prompt。

    返回空字符串表示无需校准。
    """
    path = _calibration_path(domain)
    if not path.exists():
        return ""

    data = json.loads(path.read_text(encoding="utf-8"))
    calibrations = data.get("calibrations", [])
    if not calibrations:
        return ""

    # 检查校准是否过期（超过 7 天）
    analyzed_at = data.get("analyzed_at", "")
    if analyzed_at:
        try:
            dt = datetime.fromisoformat(analyzed_at)
            if (datetime.now() - dt).days > 7:
                path.unlink()
                return ""
        except ValueError:
            pass

    lines = [
        "",
        "## 动态校准指令（自动生成，请严格遵守）",
        "",
    ]
    for cal in calibrations:
        lines.append(f"- {cal['instruction']}")

    return "\n".join(lines)


def inject_calibration(domain: str, base_prompt: str) -> str:
    """将校准指令注入评分 prompt。返回完整的 prompt。"""
    calibration = get_calibration_instructions(domain)
    if not calibration:
        return base_prompt
    return base_prompt + calibration


def run_calibration_check(domain: str, days: int = 7) -> dict:
    """运行校准分析。在管道执行后调用。"""
    return analyze_and_calibrate(domain, days)
