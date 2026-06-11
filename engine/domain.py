"""领域加载器：读取 domains/<name>/ 下的配置，组装成引擎可用的结构。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from engine.config import settings
from engine.models import SourceDef


class DomainConfig:
    """一个领域的完整配置。"""

    def __init__(self, domain_dir: Path):
        self.dir = domain_dir
        self.name = domain_dir.name

        self.sources: list[SourceDef] = self._load_sources()
        self.scoring_prompt: str = self._load_text("scoring.md")
        self.pre_filter_prompt: str = self._load_text("pre_filter.md")
        self.briefing_prompt: str = self._load_text("briefing.md", optional=True)
        self.categories: dict = self._load_yaml("categories.yaml")
        self.category_freshness: dict[str, int] = self._load_category_freshness()
        self.output_template: Optional[str] = self._load_text("daily_report.md", optional=True)
        self.keywords: list[str] = self._load_keywords()

    def _load_category_freshness(self) -> dict[str, int]:
        """加载每个分类的新鲜度天数配置。"""
        result = {}
        for cat in self.categories.get("categories", []):
            cat_id = cat.get("id", "")
            days = cat.get("freshness_days", 7)
            if cat_id:
                result[cat_id] = days
        return result

    def _load_keywords(self) -> list[str]:
        raw = self._load_yaml("keywords.yaml")
        if not raw:
            return []
        return raw.get("keywords", [])

    def _load_sources(self) -> list[SourceDef]:
        raw = self._load_yaml("sources.yaml")
        if not raw:
            return []
        return [SourceDef(**s) for s in raw.get("sources", [])]

    def _load_yaml(self, filename: str) -> dict:
        path = self.dir / filename
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_text(self, filename: str, optional: bool = False) -> str:
        path = self.dir / filename
        if not path.exists():
            if optional:
                return ""
            raise FileNotFoundError(f"领域 {self.name} 缺少必要配置: {filename}")
        return path.read_text(encoding="utf-8")


def load_domain(name: Optional[str] = None) -> DomainConfig:
    """加载指定领域配置，默认使用 settings.domain。"""
    name = name or settings.domain
    domain_dir = settings.project_root / "domains" / name
    if not domain_dir.exists():
        raise FileNotFoundError(f"领域目录不存在: {domain_dir}")
    return DomainConfig(domain_dir)
