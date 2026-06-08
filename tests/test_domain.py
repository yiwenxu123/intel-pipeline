"""Domain 配置加载测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.domain import DomainConfig, load_domain


# ── DomainConfig 基础加载 ──

def test_load_sources(domain_dir):
    dc = DomainConfig(domain_dir)
    assert len(dc.sources) == 1
    assert dc.sources[0].id == "test_src"
    assert dc.sources[0].name == "测试信源"


def test_load_categories(domain_dir):
    dc = DomainConfig(domain_dir)
    cats = dc.categories.get("categories", [])
    assert len(cats) == 2
    assert cats[0]["id"] == "policy"
    assert cats[1]["name"] == "行业动态"


def test_load_keywords(domain_dir):
    dc = DomainConfig(domain_dir)
    assert dc.keywords == ["测试", "示例"]


def test_load_scoring_prompt(domain_dir):
    dc = DomainConfig(domain_dir)
    assert dc.scoring_prompt == "评分 prompt"


def test_load_pre_filter_prompt(domain_dir):
    dc = DomainConfig(domain_dir)
    assert dc.pre_filter_prompt == "预筛 prompt"


# ── category_freshness ──

def test_category_freshness(domain_dir):
    dc = DomainConfig(domain_dir)
    assert dc.category_freshness["policy"] == 30
    assert dc.category_freshness["industry"] == 7


# ── 缺失文件处理 ──

def test_missing_required_file_raises(tmp_path):
    d = tmp_path / "bad-domain"
    d.mkdir()
    (d / "sources.yaml").write_text("sources: []", encoding="utf-8")
    # 缺少 categories.yaml、scoring.md、pre_filter.md
    with pytest.raises(FileNotFoundError):
        DomainConfig(d)


def test_missing_optional_keywords(tmp_path):
    d = tmp_path / "no-kw-domain"
    d.mkdir()
    (d / "sources.yaml").write_text("sources: []", encoding="utf-8")
    (d / "categories.yaml").write_text("{}", encoding="utf-8")
    (d / "scoring.md").write_text("prompt", encoding="utf-8")
    (d / "pre_filter.md").write_text("prompt", encoding="utf-8")
    dc = DomainConfig(d)
    assert dc.keywords == []


# ── fresh domain config ──

def test_fresh_domain_config(tmp_path):
    d = tmp_path / "fresh-domain"
    d.mkdir()
    (d / "sources.yaml").write_text(
        "sources:\n"
        "  - id: s1\n    name: 源1\n    kind: rss\n"
        "    url: https://example.com/f\n    tier: T1\n    lang: zh\n",
        encoding="utf-8",
    )
    (d / "categories.yaml").write_text(
        json.dumps({"categories": [
            {"id": "c1", "name": "分类1", "freshness_days": 14}
        ]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (d / "keywords.yaml").write_text("keywords: []", encoding="utf-8")
    (d / "scoring.md").write_text("prompt", encoding="utf-8")
    (d / "pre_filter.md").write_text("prompt", encoding="utf-8")
    dc = DomainConfig(d)
    assert dc.name == "fresh-domain"
    assert dc.category_freshness["c1"] == 14


# ── load_domain 使用 settings ──

def test_load_domain_from_settings(domain_dir):
    from engine.config import settings
    original_root = settings.project_root
    # load_domain 在 project_root/domains/<name> 下查找，需创建 domains 目录
    domains_parent = domain_dir.parent / "domains"
    domains_parent.mkdir(exist_ok=True)
    import shutil
    shutil.copytree(str(domain_dir), str(domains_parent / "test-domain"))
    settings.project_root = domain_dir.parent
    try:
        dc = load_domain("test-domain")
        assert dc.name == "test-domain"
    finally:
        settings.project_root = original_root
