"""单轮评分流水线（无预筛）：直接对条目批量评分。"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import threading

from engine.config import settings
from engine.domain import DomainConfig
from engine.filter.enrichment import scoring_input_text
from engine.filter.llm_client import chat
from engine.filter.quality_gates import normalize_content_type
from engine.models import RawItem, ScoredItem, FilterResult

# 并行评分最大线程数
SCORE_MAX_PARALLEL = 3

logger = logging.getLogger(__name__)


class ScoreStats:
    """线程安全的评分过程统计。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._stats: dict[str, int] = {
            "json_parse_failures": 0,
            "retry_success": 0,
            "batch_retries": 0,
        }

    def reset(self):
        with self._lock:
            self._stats = {"json_parse_failures": 0, "retry_success": 0, "batch_retries": 0}

    def increment(self, key: str, value: int = 1):
        with self._lock:
            self._stats[key] = self._stats.get(key, 0) + value

    def get_stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)


# 模块级单例
_score_stats = ScoreStats()


def reset_score_stats() -> None:
    _score_stats.reset()


def get_score_stats() -> dict[str, int]:
    return _score_stats.get_stats()


def pre_filter_items(
    items: list[RawItem],
    domain: DomainConfig,
    batch_size: int = 20,
) -> tuple[list[RawItem], int]:
    """低成本预筛：用 pre_filter 模型去掉明显无关条目。"""
    if not items:
        return [], 0

    system = domain.pre_filter_prompt
    passed: list[RawItem] = []
    skipped = 0

    for batch_start in range(0, len(items), batch_size):
        batch = items[batch_start : batch_start + batch_size]
        lines = []
        for idx, item in enumerate(batch, 1):
            content = (item.content or "")[:400]
            lines.append(f"{idx}. 标题：{item.title}\n   内容：{content}\n   链接：{item.url}")

        user_msg = (
            f"请对以下 {len(batch)} 条信息做预筛（Y=保留，N=过滤）。\n"
            "输出格式：序号 | Y/N | 简短理由\n\n" + "\n\n".join(lines)
        )
        response = chat(
            model=settings.llm_pre_filter_model,
            system=system,
            user=user_msg,
            temperature=0.1,
        )
        decisions = _parse_prefilter_response(response, len(batch))
        for idx, item in enumerate(batch):
            keep = decisions.get(idx + 1, True)
            if keep:
                passed.append(item)
            else:
                skipped += 1

    logger.info(f"预筛完成：{len(passed)}/{len(items)} 条通过，过滤 {skipped} 条")
    return passed, skipped


def _parse_prefilter_response(text: str, expected: int) -> dict[int, bool]:
    """解析预筛响应：{序号: 是否保留}。"""
    import re

    decisions: dict[int, bool] = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\s*\|\s*([YNyn])", line)
        if m:
            num = int(m.group(1))
            decisions[num] = m.group(2).upper() == "Y"
    # 未出现在响应中的条目默认保留，避免误杀
    for i in range(1, expected + 1):
        decisions.setdefault(i, True)
    return decisions


def _score_batch(
    batch: list[RawItem], batch_offset: int, system: str, domain_name: str
) -> list[ScoredItem]:
    """处理单批评分，返回 ScoredItem 列表。供 ThreadPoolExecutor 调用。"""
    # 构建批量输入
    parts = []
    for idx, item in enumerate(batch):
        original_source = item.extra.get("original_source", item.source_id) if item.extra else item.source_id
        body = scoring_input_text(item) or "(正文过短，请结合标题谨慎评分)"
        parts.append(
            f"条目 {idx+1}:\n"
            f"  标题：{item.title}\n"
            f"  来源：{item.source_id}（原始来源：{original_source}）\n"
            f"  内容：{body}\n"
            f"  链接：{item.url}"
        )

    total_in_batch = len(batch)
    user_msg = (
        f"请对以下 {total_in_batch} 条情报逐一评分并分类。\n"
        "请输出一个 JSON 数组，每个元素包含 score/category/tags/title/summary/key_points/reason/content_type。\n\n"
        + "\n\n".join(parts)
    )

    response = chat(
        model=settings.llm_scoring_model,
        system=system,
        user=user_msg,
        temperature=0.2,
    )

    results = _parse_json_array(response)
    if not results:
        _score_stats.increment("json_parse_failures", total_in_batch)

    # 解析结果不足时，逐条重试
    if 0 < len(results) < total_in_batch:
        missing_indices = [j for j in range(total_in_batch) if j >= len(results)]
        _score_stats.increment("batch_retries")
        logger.warning(
            f"评分结果不足：收到 {len(results)}/{total_in_batch} 条，逐条重试 {len(missing_indices)} 条"
        )
        for mi in missing_indices:
            retry_item = batch[mi]
            retry_msg = (
                "请对以下情报评分并分类，输出一个 JSON 对象，包含 score/category/tags/title/summary/key_points/reason/content_type。\n\n"
                f"标题：{retry_item.title}\n"
                f"来源：{retry_item.source_id}\n"
                f"内容：{scoring_input_text(retry_item) or '(正文过短)'}\n"
                f"链接：{retry_item.url}"
            )
            retry_resp = chat(
                model=settings.llm_scoring_model, system=system, user=retry_msg, temperature=0.2
            )
            retry_results = _parse_json_array(retry_resp)
            if retry_results:
                _score_stats.increment("retry_success")
                results.append(retry_results[0])
            else:
                _score_stats.increment("json_parse_failures")
                results.append({})

    scored: list[ScoredItem] = []
    for j in range(total_in_batch):
        item = batch[j]
        if j < len(results):
            r = results[j] or {}
        else:
            r = {}
            logger.warning(f"评分结果缺失 [{item.title[:30]}]")

        score_val = float(r.get("score", 5.0))
        category_val = r.get("category", "uncategorized")
        summary_val = r.get("summary", item.title)
        reason_val = r.get("reason", "")
        tags_val = r.get("tags", [])
        title_val = r.get("title", "") or ""  # LLM 翻译后的中文标题
        key_points_val = r.get("key_points", [])
        key_points_val = (
            key_points_val if isinstance(key_points_val, list) else []
        )
        entities_val = r.get("entities", [])
        entities_val = entities_val if isinstance(entities_val, list) else []
        content_type_val = normalize_content_type(r.get("content_type"))
        source_display_val = item.extra.get("original_source", "") if item.extra else ""
        if not source_display_val:
            source_display_val = item.source_id

        scored.append(
            ScoredItem(
                raw=item,
                score=score_val,
                category=category_val,
                tags=tags_val,
                summary=summary_val,
                key_points=key_points_val,
                reason=reason_val,
                entities=entities_val,
                source_display=source_display_val,
                title_display=title_val,
                content_type=content_type_val,
            )
        )

    logger.info(f"评分批次完成：{len(scored)} 条")
    return scored


def score_items(
    items: list[RawItem],
    domain: DomainConfig,
    batch_size: int = 15,
    parallel: bool = True,
) -> list[ScoredItem]:
    """第二轮：强模型批量评分，支持并行处理。

    Args:
        parallel: 是否并行处理多个批次（默认 True）。设为 False 可降级为串行。
    """
    if not items:
        return []

    reset_score_stats()

    # 注入评分校准指令（如果有）
    try:
        from engine.evolution.scoring_injector import inject_calibration
        system = inject_calibration(domain.name, domain.scoring_prompt)
    except Exception:
        system = domain.scoring_prompt

    batches = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]

    if len(batches) <= 1 or not parallel:
        # 只有一个批次或串行模式，直接处理
        scored: list[ScoredItem] = []
        for i, batch in enumerate(batches):
            scored.extend(_score_batch(batch, i * batch_size, system, domain.name))
        logger.info(f"评分完成：{len(scored)} 条")
        return scored

    # 并行处理多个批次
    scored: list[ScoredItem] = [None] * len(items)  # type: ignore
    with concurrent.futures.ThreadPoolExecutor(max_workers=SCORE_MAX_PARALLEL) as executor:
        futures: dict[concurrent.futures.Future, int] = {}
        for i, batch in enumerate(batches):
            future = executor.submit(_score_batch, batch, i * batch_size, system, domain.name)
            futures[future] = i

        for future in concurrent.futures.as_completed(futures):
            try:
                batch_results = future.result()
                batch_idx = futures[future]
                start = batch_idx * batch_size
                for j, si in enumerate(batch_results):
                    scored[start + j] = si
            except Exception as e:
                logger.error(f"评分批次处理失败: {e}")
                # 失败的批次用 fallback 填充
                batch_idx = futures[future]
                start = batch_idx * batch_size
                batch = batches[batch_idx]
                for j, item in enumerate(batch):
                    scored[start + j] = ScoredItem(
                        raw=item,
                        score=5.0,
                        category="uncategorized",
                        summary=item.title,
                        reason=f"评分失败: {e}",
                    )

    scored = [s for s in scored if s is not None]
    logger.info(f"评分完成：{len(scored)} 条")
    return scored


def _parse_json_array(text: str) -> list[dict]:
    """从 LLM 响应中提取 JSON 数组，兼容 markdown 代码块和常见格式问题。"""
    import re

    json_str = text.strip()

    # 1. 提取代码块内容（支持 ```json ... ``` 和 ``` ... ```）
    code_block = re.search(r'```(?:json)?\s*\n?(.*?)```', json_str, re.DOTALL)
    if code_block:
        json_str = code_block.group(1).strip()
    elif "```" in json_str:
        # 兜底：没有配对的代码块
        json_str = json_str.split("```")[1]
        if json_str.startswith("json"):
            json_str = json_str[4:]
        json_str = json_str.strip()

    # 2. 尝试直接解析
    try:
        result = json.loads(json_str)
        if isinstance(result, list):
            return result
        return [result]
    except json.JSONDecodeError:
        pass

    # 3. 尝试清理常见问题后重新解析
    # 去掉尾部逗号：{"a":1,} → {"a":1}
    cleaned = re.sub(r',\s*([}\]])', r'\1', json_str)
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
        return [result]
    except json.JSONDecodeError:
        pass

    # 4. 尝试修复不完整的 JSON
    # 如果 JSON 被截断，尝试补全
    if json_str.startswith('[') and not json_str.endswith(']'):
        # 尝试补全最后一个对象
        last_brace = json_str.rfind('}')
        if last_brace > 0:
            json_str = json_str[:last_brace + 1] + ']'
            try:
                result = json.loads(json_str)
                if isinstance(result, list):
                    return result
                return [result]
            except json.JSONDecodeError:
                pass

    # 5. 基于括号匹配逐个提取 JSON 对象，适应未转义引号问题
    def _extract_objects(s: str) -> list[str]:
        """用括号计数提取顶层 JSON 对象。不跟踪字符串状态——假设值不含未转义的花括号。"""
        objects = []
        depth = 0
        start = -1
        for i, c in enumerate(s):
            if c == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0 and start >= 0:
                    objects.append(s[start:i+1])
        return objects

    # 如果 JSON 字符串以 [ 开头，尝试逐个提取对象
    if json_str.strip().startswith('['):
        objs = _extract_objects(json_str)
        if objs:
            results = []
            for obj in objs:
                # 尝试直接解析
                try:
                    results.append(json.loads(obj))
                except json.JSONDecodeError:
                    # 清理尾部逗号再试
                    fixed = re.sub(r',\s*([}\]])', r'\1', obj)
                    try:
                        results.append(json.loads(fixed))
                    except json.JSONDecodeError:
                        pass
            if results:
                return results

    # 6. 兜底：直接从文本中提取第一个 [...] 块
    match = re.search(r'\[\s*\{.*?\}\s*\]', json_str, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return result
            return [result]
        except json.JSONDecodeError:
            pass

    # 7. 全部失败 — 记录原始响应供调试
    logger.warning(f"JSON 解析失败，响应长度 {len(text)} 字符，前300字: {text[:300]}")
    # 保存完整响应用于离线调试
    try:
        err_dir = settings.project_root / "data" / "llm_errors"
        err_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        err_path = err_dir / f"parse_fail_{ts}.txt"
        err_path.write_text(text, encoding="utf-8")
        logger.info(f"原始 LLM 响应已保存: {err_path}")
    except Exception:
        pass
    return []


def run_pipeline(items: list[RawItem], domain: DomainConfig) -> FilterResult:
    """单轮评分流水线（无预筛），返回带统计的结果。"""
    import time
    start = time.time()
    total_input = len(items)

    scored = score_items(items, domain)
    scored.sort(key=lambda x: x.score, reverse=True)

    duration = time.time() - start
    score_batches = (total_input + 14) // 15  # batch_size=15
    llm_calls = score_batches

    return FilterResult(
        scored_items=scored,
        pre_filter_total=total_input,
        pre_filter_passed=total_input,
        scored_total=len(scored),
        llm_calls=llm_calls,
        duration_seconds=round(duration, 2),
    )
