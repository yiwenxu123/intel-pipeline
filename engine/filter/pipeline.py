"""两轮筛选流水线：预筛 → 评分。"""

from __future__ import annotations

import json
import logging
from typing import Optional

from engine.config import settings
from engine.domain import DomainConfig
from engine.filter.llm_client import chat
from engine.models import RawItem, ScoredItem

logger = logging.getLogger(__name__)


def pre_filter(items: list[RawItem], domain: DomainConfig, batch_size: int = 20) -> list[RawItem]:
    """第一轮：低成本模型预筛，去掉无关内容。"""
    if not items:
        return []

    system = domain.pre_filter_prompt
    kept: list[RawItem] = []

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        # 构建输入
        input_lines = []
        for idx, item in enumerate(batch):
            input_lines.append(f"{idx+1}. [{item.source_id}] {item.title}\n   {item.content[:200]}")
        user_msg = "\n".join(input_lines)

        response = chat(
            model=settings.llm_pre_filter_model,
            system=system,
            user=user_msg,
            temperature=0.1,
        )

        # 解析结果
        for line in response.strip().split("\n"):
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue
            try:
                idx = int(parts[0]) - 1
            except ValueError:
                continue
            if parts[1].upper() == "Y" and 0 <= idx < len(batch):
                kept.append(batch[idx])

    logger.info(f"预筛完成：{len(items)} → {len(kept)} 条")
    return kept


def score_items(items: list[RawItem], domain: DomainConfig, batch_size: int = 5) -> list[ScoredItem]:
    """第二轮：强模型批量评分（每次送 batch_size 条）。"""
    if not items:
        return []

    system = domain.scoring_prompt
    scored: list[ScoredItem] = []

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]

        # 构建批量输入
        parts = []
        for idx, item in enumerate(batch):
            original_source = item.extra.get("original_source", item.source_id) if item.extra else item.source_id
            parts.append(
                f"条目 {idx+1}:\n"
                f"  标题：{item.title}\n"
                f"  来源：{item.source_id}（原始来源：{original_source}）\n"
                f"  内容：{item.content[:600]}\n"
                f"  链接：{item.url}"
            )
        user_msg = (
            "请对以下 " + str(len(batch)) + " 条情报逐一评分并分类。\n"
            "请输出一个 JSON 数组，每个元素包含 score/category/source_display/title_display/content_type/tags/summary/key_points/reason/entities。\n\n"
            + "\n\n".join(parts)
        )

        response = chat(
            model=settings.llm_scoring_model,
            system=system,
            user=user_msg,
            temperature=0.2,
        )

        # 解析 JSON 数组
        results = _parse_json_array(response)
        for j, item in enumerate(batch):
            if j < len(results):
                r = results[j]
                # 确定来源显示名：优先用 LLM 输出的 source_display，其次用原始来源，最后用 source_id
                source_display = r.get("source_display", "") or item.extra.get("original_source", "") or item.source_id
                # 确定标题：优先用 LLM 翻译的 title_display，其次用原标题
                title_display = r.get("title_display", "") or item.title
                scored.append(
                    ScoredItem(
                        raw=item,
                        score=float(r.get("score", 0)),
                        category=r.get("category", ""),
                        tags=r.get("tags", []),
                        summary=r.get("summary", item.title),
                        key_points=r.get("key_points", []),
                        reason=r.get("reason", ""),
                        entities=r.get("entities", []),
                        source_display=source_display,
                        title_display=title_display,
                        content_type=r.get("content_type", "news"),
                    )
                )
            else:
                logger.warning(f"评分结果不足 [{item.title[:30]}]")
                scored.append(
                    ScoredItem(
                        raw=item,
                        score=5.0,
                        category="uncategorized",
                        summary=item.title,
                        reason="评分结果缺失，保留待人工审核",
                    )
                )

        logger.info(f"评分进度：{min(i + batch_size, len(items))}/{len(items)}")

    logger.info(f"评分完成：{len(scored)} 条")
    return scored


def _parse_json_array(text: str) -> list[dict]:
    """从 LLM 响应中提取 JSON 数组，兼容 markdown 代码块。"""
    json_str = text.strip()
    if "```" in json_str:
        json_str = json_str.split("```")[1]
        if json_str.startswith("json"):
            json_str = json_str[4:]
    json_str = json_str.strip()
    # 尝试直接解析
    try:
        result = json.loads(json_str)
        if isinstance(result, list):
            return result
        return [result]
    except json.JSONDecodeError:
        pass
    # 尝试提取第一个 [ ... ] 块
    import re
    match = re.search(r'\[\s*\{.*?\}\s*\]', json_str, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    logger.warning(f"JSON 解析失败，原始文本前200字: {text[:200]}")
    return []


def run_pipeline(items: list[RawItem], domain: DomainConfig) -> list[ScoredItem]:
    """完整筛选流水线：预筛 → 评分。"""
    filtered = pre_filter(items, domain)
    scored = score_items(filtered, domain)
    # 按分数降序
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored
