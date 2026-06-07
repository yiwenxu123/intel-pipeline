# 养老/大健康情报引擎 — 信源扩展指南

## 快速添加新信源

在 `domains/elderly-care/sources.yaml` 末尾追加即可，引擎自动识别。

### 添加 RSS 信源

```yaml
  - id: your_new_source          # 唯一标识
    name: 信源名称                # 显示名
    kind: rss                     # 源类型
    url: https://example.com/feed # RSS 地址
    tier: T1                      # T1 / T1.5 / T2
    lang: zh                      # zh / en
    keywords_filter: false        # 垂直源用 false，通用源用 true
    tags: [养老, 产业]             # 标签
```

### 添加网页信源

```yaml
  - id: your_web_source
    name: 信源名称
    kind: web
    url: https://example.com/
    tier: T1
    lang: zh
    keywords_filter: false
    selectors:                    # CSS 选择器（可选，不配则通用提取）
      article: ".article-item"    # 文章列表容器
      title: "a"                  # 标题元素
      date: ".date"               # 日期元素（可选）
    tags: [养老, 研究]
```

### 添加 SearXNG 搜索源

```yaml
  - id: searxng_your_search
    name: 搜索描述
    kind: searxng
    url: http://10.207.251.137:8080  # SearXNG 地址
    tier: T1.5
    lang: zh
    keywords_filter: false
    selectors:
      url_filter: mp.weixin.qq.com   # 只保留匹配此 URL 的结果（可选）
      search_queries:                # 搜索词列表
        - 养老 最新政策
        - 银发经济 产业
    tags: [养老, 公众号]
```

## 层级说明

| 层 | 策略 | 何时用 |
|---|---|---|
| **T1** | 垂直源，天然产出领域内容 | 养老公众号、民政部、AgeClub |
| **T1.5** | 通用源 + 关键词过滤，或搜索补充 | 百度热搜、SearXNG |
| **T2** | 参考源，用于发现新话题 | 智慧养老网、养老问问 |

## 关键词过滤

当 `keywords_filter: true` 时，采集后立即用 `keywords.yaml` 中的关键词过滤，只保留匹配条目。

适用于：百度/微博/知乎等通用热榜。
不适用于：养老公众号、AgeClub 等垂直源。

## 关键词管理

编辑 `domains/elderly-care/keywords.yaml`，每行一个关键词。匹配规则：标题或内容中包含任一关键词即保留。

## 日期提取优先级

1. RSS 源自带 `published` 字段
2. 网页源从 CSS 选择器 `date` 提取
3. 从 URL 正则提取（如 `/202606/t20260606_`）
4. 从文章详情页正文提取
5. 无日期 → 不入库（宁缺毋滥）

## 测试新信源

```bash
# 测试单个信源
python3 -c "
from engine.domain import load_domain
from engine.fetcher.rss_fetcher import fetch_rss

domain = load_domain('elderly-care')
for s in domain.sources:
    if s.id == 'your_new_source':
        items = fetch_rss(s)
        print(f'{len(items)} 条')
        for i in items[:3]:
            print(f'  {i.title[:50]}')
"
```
