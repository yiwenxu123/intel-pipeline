"""数据模型：整个引擎的核心数据结构。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceKind(str, Enum):
    RSS = "rss"
    WEB = "web"
    API = "api"
    SEARXNG = "searxng"
    AGECLUB = "ageclub"


class SourceType(str, Enum):
    """信源类型，用于差异化质量评估。"""
    POLICY = "policy"        # 政策源（政府、监管机构）
    RESEARCH = "research"    # 研究机构（学术、智库）
    MEDIA = "media"          # 行业媒体（垂直媒体、公众号）
    HOTLIST = "hotlist"      # 热榜源（百度、微博、知乎）
    OVERSEAS = "overseas"    # 海外信源
    GENERAL = "general"      # 通用信源（默认）


# 信源类型对应的评估参数
SOURCE_TYPE_CONFIG = {
    SourceType.POLICY: {
        "min_yield_rate": 0.01,      # 最低产出率 1%
        "observation_days": 30,       # 观察期 30 天
        "auto_disable": False,        # 不自动禁用
        "description": "政策源（政府、监管机构）",
    },
    SourceType.RESEARCH: {
        "min_yield_rate": 0.02,      # 最低产出率 2%
        "observation_days": 30,       # 观察期 30 天
        "auto_disable": False,        # 不自动禁用
        "description": "研究机构（学术、智库）",
    },
    SourceType.MEDIA: {
        "min_yield_rate": 0.05,      # 最低产出率 5%
        "observation_days": 14,       # 观察期 14 天
        "auto_disable": True,         # 自动禁用
        "description": "行业媒体（垂直媒体、公众号）",
    },
    SourceType.HOTLIST: {
        "min_yield_rate": 0.03,      # 最低产出率 3%
        "observation_days": 7,        # 观察期 7 天
        "auto_disable": True,         # 自动禁用
        "description": "热榜源（百度、微博、知乎）",
    },
    SourceType.OVERSEAS: {
        "min_yield_rate": 0.03,      # 最低产出率 3%
        "observation_days": 14,       # 观察期 14 天
        "auto_disable": True,         # 自动禁用
        "description": "海外信源",
    },
    SourceType.GENERAL: {
        "min_yield_rate": 0.05,      # 最低产出率 5%
        "observation_days": 7,        # 观察期 7 天
        "auto_disable": True,         # 自动禁用
        "description": "通用信源（默认）",
    },
}


class SourceDef(BaseModel):
    """一条信源定义，来自 sources.yaml。"""

    id: str
    name: str
    kind: SourceKind
    url: str
    tier: str = "T2"  # T1 / T1.5 / T2
    type: SourceType = SourceType.GENERAL  # 信源类型，用于差异化质量评估
    lang: str = "zh"  # zh / en / fr
    schedule: str = "0 */2 * * *"  # cron 表达式
    selectors: Optional[dict] = None  # CSS 选择器，web 类型用
    enabled: bool = True
    confirmed: bool = False  # 人工确认标记，不会被自动禁用
    tags: list[str] = Field(default_factory=list)
    keywords_filter: bool = False  # 是否用领域关键词过滤


class RawItem(BaseModel):
    """采集到的原始条目，未经筛选。"""

    source_id: str
    title: str
    url: str
    content: str = ""  # 摘要或全文
    published: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=datetime.now)
    lang: str = "zh"
    extra: dict = Field(default_factory=dict)


class ScoredItem(BaseModel):
    """经过 LLM 评分后的条目。"""

    raw: RawItem
    score: float = 0.0  # 0-10
    category: str = ""  # 板块分类
    tags: list[str] = Field(default_factory=list)
    summary: str = ""  # LLM 生成的中文摘要
    key_points: list[str] = Field(default_factory=list)  # 核心要点
    reason: str = ""  # 推荐理由
    entities: list[str] = Field(default_factory=list)  # 涉及的国家/企业/人物
    source_display: str = ""  # 来源显示名
    title_display: str = ""  # 中文标题（外文翻译后）
    content_type: str = "news"  # news/policy/report/analysis/research/opinion


class DailyReport(BaseModel):
    """每日情报简报。"""

    date: str  # YYYY-MM-DD
    domain: str
    items: list[ScoredItem]
    stats: dict = Field(default_factory=dict)  # 抓取数、精选数、精选率等


class FetchError(BaseModel):
    """单个信源采集错误。"""

    source_id: str
    error: str
    error_type: str  # timeout / parse_error / http_error / unknown


class FetchResult(BaseModel):
    """采集结果。"""

    new_items: list[RawItem]
    errors: list[FetchError] = Field(default_factory=list)
    duration_seconds: float = 0.0
    sources_total: int = 0
    sources_success: int = 0


class FilterResult(BaseModel):
    """筛选结果统计。"""

    scored_items: list[ScoredItem]
    pre_filter_total: int = 0
    pre_filter_passed: int = 0
    scored_total: int = 0
    llm_calls: int = 0
    duration_seconds: float = 0.0
