"""Fetcher 单元测试（mock HTTP，不依赖网络）。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from engine.fetcher.rss_fetcher import fetch_rss
from engine.fetcher.web_fetcher import fetch_web
from engine.fetcher.runner import _match_keywords, fetch_all
from engine.fetcher.date_verifier import verify_dates_batch
from engine.models import RawItem, SourceDef, SourceKind


RSS_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Test Feed</title>
  <item>
    <title>中非贸易额创新高</title>
    <link>https://example.com/article1</link>
    <description>2024年中非贸易额达到历史新高</description>
    <pubDate>Mon, 01 Jan 2024 08:00:00 GMT</pubDate>
  </item>
  <item>
    <title>肯尼亚基建项目启动</title>
    <link>https://example.com/article2</link>
    <description>中国企业在肯尼亚承建公路项目</description>
    <pubDate>Tue, 02 Jan 2024 09:00:00 GMT</pubDate>
  </item>
  <item>
    <title></title>
    <link>https://example.com/article3</link>
  </item>
</channel>
</rss>"""


@patch("engine.fetcher.rss_fetcher.httpx.get")
def test_fetch_rss_basic(mock_get):
    mock_resp = MagicMock()
    mock_resp.text = RSS_FEED_XML
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    source = SourceDef(id="test_rss", name="Test", kind=SourceKind.RSS,
                       url="https://example.com/feed", lang="zh")
    items = fetch_rss(source)

    assert len(items) == 2
    assert items[0].title == "中非贸易额创新高"
    assert items[0].url == "https://example.com/article1"
    assert "中非贸易额" in items[0].content
    assert items[0].published is not None
    assert items[0].published.year == 2024

    assert items[1].title == "肯尼亚基建项目启动"
    assert items[1].url == "https://example.com/article2"


@patch("engine.fetcher.rss_fetcher.httpx.get")
def test_fetch_rss_http_error(mock_get):
    from httpx import HTTPStatusError

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock())
    mock_get.return_value = mock_resp

    source = SourceDef(id="bad_rss", name="Bad", kind=SourceKind.RSS,
                       url="https://example.com/bad", lang="zh")
    items = fetch_rss(source)
    assert items == []


@patch("engine.fetcher.rss_fetcher.httpx.get")
def test_fetch_rss_malformed(mock_get):
    mock_resp = MagicMock()
    mock_resp.text = "这不是 XML"
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    source = SourceDef(id="bad_xml", name="Bad", kind=SourceKind.RSS,
                       url="https://example.com/bad", lang="zh")
    items = fetch_rss(source)
    assert items == []


HTML_PAGE = """<!DOCTYPE html>
<html><body>
<div class="news-list">
  <li><a href="/article1">习近平会见非洲国家领导人</a><i>2024-01-01</i></li>
  <li><a href="/article2">中非合作论坛成果丰硕</a><i>2024-01-02</i></li>
</div>
</body></html>"""


@patch("engine.fetcher.web_fetcher.httpx.get")
def test_fetch_web_basic(mock_get):
    mock_resp = MagicMock()
    mock_resp.text = HTML_PAGE
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    source = SourceDef(id="test_web", name="Test", kind=SourceKind.WEB,
                       url="https://example.com/news", lang="zh",
                       selectors={"article": "div.news-list li", "title": "a", "date": "i"})
    items = fetch_web(source)

    assert len(items) >= 2
    titles = [i.title for i in items]
    assert any("习近平" in t for t in titles)
    assert any("中非合作" in t for t in titles)


@patch("engine.fetcher.web_fetcher.httpx.get")
def test_fetch_web_no_selectors(mock_get):
    source = SourceDef(id="no_sel", name="Test", kind=SourceKind.WEB,
                       url="https://example.com", lang="zh")
    items = fetch_web(source)
    assert items == []


@patch("engine.fetcher.web_fetcher.httpx.get")
def test_fetch_web_http_error(mock_get):
    from httpx import HTTPStatusError

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock())
    mock_get.return_value = mock_resp

    source = SourceDef(id="err_web", name="Err", kind=SourceKind.WEB,
                       url="https://example.com/err", lang="zh",
                       selectors={"article": "li", "title": "a"})
    items = fetch_web(source)
    assert items == []


def test_match_keywords_hit():
    item = RawItem(source_id="test", title="中非贸易额创新高", url="https://example.com",
                   content="2024年中非双边贸易额增长", lang="zh")
    assert _match_keywords(item, ["中非"])
    assert _match_keywords(item, ["贸易额"])
    assert _match_keywords(item, ["双边"])


def test_match_keywords_miss():
    item = RawItem(source_id="test", title="美国股市大涨", url="https://example.com",
                   content="纳斯达克指数创新高", lang="zh")
    assert not _match_keywords(item, ["中非", "非洲", "贸易"])


def test_match_keywords_case_insensitive():
    item = RawItem(source_id="test", title="China-Africa Trade", url="https://example.com",
                   content="China and Africa", lang="en")
    assert _match_keywords(item, ["china-africa"])
    assert _match_keywords(item, ["africa"])


def test_fetch_all_with_mocks(domain_dir, tmp_path):
    from engine.domain import DomainConfig
    from engine.store import Store

    domain = DomainConfig(domain_dir)

    db_path = tmp_path / "test_fetch.db"
    store = Store(db_path)

    now = datetime.now(timezone.utc)
    mock_items = [
        RawItem(source_id="test_src", title="源A第一条", url="https://example.com/a1",
                content="内容", lang="zh", published=now),
        RawItem(source_id="test_src", title="源A第二条", url="https://example.com/a2",
                content="内容", lang="zh", published=now),
    ]

    with patch("engine.fetcher.runner.fetch_rss") as mock_fetch_rss:
        mock_fetch_rss.return_value = mock_items
        result = fetch_all(domain, store, max_workers=1)

    assert result.sources_total == 1
    assert result.sources_success == 1
    assert len(result.new_items) == 2

    saved = store.conn.execute("SELECT title FROM raw_items").fetchall()
    saved_titles = [r["title"] for r in saved]
    assert "源A第一条" in saved_titles
    assert "源A第二条" in saved_titles

    store.close()


def test_fetch_all_with_keywords_filter(domain_dir, tmp_path):
    import yaml
    from pathlib import Path
    from engine.domain import DomainConfig
    from engine.store import Store

    domain_dir_path = Path(domain_dir)
    raw = yaml.safe_load((domain_dir_path / "sources.yaml").read_text(encoding="utf-8"))
    raw["sources"] = [{
        "id": "src_filtered",
        "name": "带过滤",
        "kind": "rss",
        "url": "https://example.com/filtered",
        "tier": "T2",
        "lang": "zh",
        "keywords_filter": True,
    }]
    (domain_dir_path / "sources.yaml").write_text(
        yaml.dump(raw, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    (domain_dir_path / "keywords.yaml").write_text(
        "keywords:\n  - 中非\n  - 非洲\n", encoding="utf-8",
    )

    domain = DomainConfig(domain_dir_path)
    db_path = tmp_path / "test_kw.db"
    store = Store(db_path)

    now = datetime.now(timezone.utc)
    mock_items = [
        RawItem(source_id="src_filtered", title="中非合作新进展", url="https://example.com/b1",
                content="关于中非贸易", lang="zh", published=now),
        RawItem(source_id="src_filtered", title="美国经济数据", url="https://example.com/b2",
                content="GDP增长", lang="zh", published=now),
        RawItem(source_id="src_filtered", title="非洲市场分析", url="https://example.com/b3",
                content="非洲市场", lang="zh", published=now),
    ]

    with patch("engine.fetcher.runner.fetch_rss") as mock_fetch_rss:
        mock_fetch_rss.return_value = mock_items
        result = fetch_all(domain, store, max_workers=1)

    assert len(result.new_items) == 2
    saved = store.conn.execute("SELECT title FROM raw_items").fetchall()
    saved_titles = [r["title"] for r in saved]
    assert "中非合作新进展" in saved_titles
    assert "美国经济数据" not in saved_titles
    assert "非洲市场分析" in saved_titles

    store.close()


def test_fetch_all_error_handling(domain_dir, tmp_path):
    import yaml
    from pathlib import Path
    from engine.domain import DomainConfig
    from engine.store import Store

    domain_dir_path = Path(domain_dir)
    raw = yaml.safe_load((domain_dir_path / "sources.yaml").read_text(encoding="utf-8"))
    raw["sources"].append({
        "id": "bad_src",
        "name": "坏信源",
        "kind": "rss",
        "url": "https://example.com/bad",
        "tier": "T2",
        "lang": "zh",
    })
    (domain_dir_path / "sources.yaml").write_text(
        yaml.dump(raw, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )

    domain = DomainConfig(domain_dir_path)
    db_path = tmp_path / "test_err.db"
    store = Store(db_path)

    now = datetime.now(timezone.utc)
    mock_good = [
        RawItem(source_id="test_src", title="正常条目", url="https://example.com/g1",
                content="内容", lang="zh", published=now),
    ]

    with patch("engine.fetcher.runner.fetch_rss") as mock_fetch:
        def side_effect(source):
            if source.id == "test_src":
                return mock_good
            raise ConnectionError("模拟网络错误")
        mock_fetch.side_effect = side_effect

        result = fetch_all(domain, store, max_workers=1)

    assert len(result.new_items) == 1
    assert len(result.errors) == 1
    assert result.errors[0].source_id == "bad_src"
    assert result.sources_success == 1
    assert result.sources_total == 2

    store.close()


# ── 全文提取 ──

FULL_HTML = """<!DOCTYPE html>
<html><head><title>中非贸易额创新高</title></head>
<body>
<nav>导航栏链接</nav>
<article>
<h1>中非贸易额创新高 达到2800亿美元</h1>
<p>2024年中非双边贸易额达到历史新高的2800亿美元，同比增长11%。这是中非贸易额连续第三年突破2000亿美元大关。</p>
<p>中国已连续15年成为非洲第一大贸易伙伴国。数据显示，2024年中国从非洲进口商品总额达到1200亿美元，同比增长8%。同时，中国对非洲出口达到1600亿美元，同比增长14%。非洲也是中国最大的海外承包工程市场之一，中国企业在非洲承建的蒙内铁路、亚吉铁路等项目均已投入运营。</p>
<p>专家分析认为，中非经贸合作正处于从传统贸易向产业链合作转型升级的关键阶段。未来在数字经济、绿色能源、现代农业、医疗卫生等新兴领域的合作空间广阔。中国企业应抓住机遇，在非洲布局新能源、跨境电商等新业态。</p>
<p>商务部研究院发布报告指出，中非合作论坛成果持续显现，越来越多的非洲国家希望通过与中国合作实现经济多元化发展。截至目前，已有52个非洲国家及非盟委员会同中国签署了共建"一带一路"合作文件。</p>
</article>
<footer>版权信息 © 2024</footer>
</body></html>"""


@patch("engine.fetcher.full_text_fetcher.httpx.get")
def test_fetch_and_extract(mock_get):
    """全文提取：从 HTML 中提取正文，排除导航/页脚。"""
    mock_resp = MagicMock()
    mock_resp.text = FULL_HTML
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    from engine.fetcher.full_text_fetcher import fetch_and_extract
    text = fetch_and_extract("https://example.com/article")

    assert text is not None
    assert "中非贸易额创新高" in text
    assert "2800亿美元" in text
    assert "导航栏" not in text  # 导航应被排除
    assert "版权信息" not in text  # footer 应被排除


def test_extract_full_text_direct():
    """直接提取 HTML 正文（不经过 HTTP）。"""
    from engine.fetcher.full_text_fetcher import extract_full_text
    text = extract_full_text(FULL_HTML)

    assert text is not None
    assert "中非贸易额创新高" in text
    assert len(text) > 100


def test_extract_full_text_minimal():
    """HTML 内容太少时返回 None。"""
    from engine.fetcher.full_text_fetcher import extract_full_text
    text = extract_full_text("<html><body><p>短文本</p></body></html>")
    assert text is None


def test_extract_full_text_no_body():
    """无正文时返回 None。"""
    from engine.fetcher.full_text_fetcher import extract_full_text
    text = extract_full_text("<html></html>")
    assert text is None


AGECLUB_NUXT_HTML = """<html><body><div id="app">
<nav>首页 品牌矩阵 研究报告 登录</nav>
<script>window.__NUXT__={data:{"article/article-detail":{id:1,
content:"<p>在老年慢病管理领域，营养干预正成为重要突破口，相关内容持续更新中，覆盖糖尿病、高血压等慢病场景。</p><p>融资额达14.5亿美元，94%患者实现零自付，商业模式获得保险支付方认可。</p><p>专家分析认为，院外代谢管理将成为银发健康服务的下一个增长极，值得产业与资本持续关注。</p>"}}}</script>
</div></body></html>"""


def test_extract_ageclub_nuxt_payload():
    """AgeClub：从 __NUXT__ payload 提取正文，不走导航壳层。"""
    from engine.fetcher.full_text_fetcher import extract_full_text
    text = extract_full_text(AGECLUB_NUXT_HTML, url="https://www.ageclub.net/article-detail/1")
    assert text is not None
    assert "营养干预" in text
    assert "14.5亿美元" in text
    assert "首页" not in text


def test_extract_rejects_nav_boilerplate_fallback():
    """通用提取：body 含站点导航时返回 None 而非误存壳层。"""
    from engine.fetcher.full_text_fetcher import extract_full_text, is_nav_boilerplate
    html = """<html><body>
    <div>首页 品牌矩阵 研究报告 产业活动 合作对接 会员专区 发布商机 搜索 登录
    某文章标题 2026-06-11 一句导语。本文来源声明。</div>
    </body></html>"""
    nav = "首页 品牌矩阵 研究报告 产业活动 合作对接 会员专区 发布商机 搜索 登录 " * 3
    assert is_nav_boilerplate(nav + "某文章标题导语")
    text = extract_full_text(html, url="https://example.com/article")
    assert text is None


@patch("engine.fetcher.full_text_fetcher.httpx.get")
def test_fetch_and_extract_http_error(mock_get):
    """HTTP 错误时返回 None。"""
    from httpx import HTTPStatusError
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = HTTPStatusError(
        "403", request=MagicMock(), response=MagicMock())
    mock_get.return_value = mock_resp

    from engine.fetcher.full_text_fetcher import fetch_and_extract
    text = fetch_and_extract("https://example.com/blocked")
    assert text is None


# ── Store: update_full_text ──


def test_store_update_full_text(store):
    """store.update_full_text 正确更新全文。"""
    item = RawItem(source_id="test", title="测试", url="https://example.com/a",
                   content="摘要")
    raw_id = store.save_raw(item)
    assert raw_id > 0

    ok = store.update_full_text("https://example.com/a", "这是完整的正文内容")
    assert ok

    row = store.conn.execute("SELECT full_text FROM raw_items WHERE id = ?",
                             (raw_id,)).fetchone()
    assert row is not None
    assert row["full_text"] == "这是完整的正文内容"


def test_store_update_full_text_nonexistent(store):
    """不存在的 URL 不影响任何行。"""
    ok = store.update_full_text("https://example.com/nonexistent", "正文")
    assert not ok


@patch("engine.fetcher.date_verifier.httpx.get")
def test_verify_dates_batch(mock_get):
    def side_effect(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = '<html></html>'
        if "article1" in str(url):
            resp.text = '<html><body><time datetime="2024-06-01">2024-06-01</time></body></html>'
        elif "article2" in str(url):
            resp.text = '<html><body><span class="date">2024-06-02</span></body></html>'
        else:
            resp.status_code = 404
        return resp

    mock_get.side_effect = side_effect

    items = [
        RawItem(source_id="test", title="A", url="https://example.com/article1",
                content="", lang="zh"),
        RawItem(source_id="test", title="B", url="https://example.com/article2",
                content="", lang="zh"),
        RawItem(source_id="test", title="C", url="https://example.com/article3",
                content="", lang="zh"),
    ]

    result = verify_dates_batch(items, max_fetches=5)
    assert "https://example.com/article1" in result
    assert "https://example.com/article2" in result
    assert len(result) <= 3
