# Intel Pipeline — 可配置的行业情报引擎

## 项目概述

这是一个**多领域可插拔的情报采集、筛选、展示系统**。目前支持两个领域：
- **中非经贸** (`china-africa`) — 中非贸易、投资、政策情报
- **银发产业** (`elderly-care`) — 养老、大健康、银发经济情报

## 架构

```
engine/                 # 通用引擎（领域无关）
├── config.py           # 全局配置（.env 驱动）
├── models.py           # 数据模型
├── domain.py           # 领域加载器
├── store.py            # SQLite 存储层
├── cli.py              # CLI 入口
├── fetcher/            # 采集模块
│   ├── rss_fetcher.py  # RSS 采集
│   ├── web_fetcher.py  # 网页采集
│   ├── ageclub_fetcher.py  # AgeClub 专用采集
│   ├── searxng_fetcher.py  # SearXNG 搜索采集
│   ├── date_extractor.py   # 日期提取
│   └── date_verifier.py    # 日期验证
├── filter/             # LLM 筛选模块
│   ├── pipeline.py     # 两轮筛选流水线
│   └── llm_client.py   # LLM 客户端
└── output/             # 输出模块
    ├── api.py          # REST API
    └── report.py       # 日报生成

domains/                # 领域配置
├── china-africa/       # 中非经贸
│   ├── sources.yaml    # 信源配置
│   ├── categories.yaml # 分类体系
│   ├── keywords.yaml   # 关键词
│   ├── scoring.md      # LLM 评分 prompt
│   ├── pre_filter.md   # LLM 预筛 prompt
│   └── web/index.html  # 前端模板
└── elderly-care/       # 银发产业
    └── (同上结构)

skills/                 # SKILL.md 文件
├── china-africa/SKILL.md
└── elderly-care/SKILL.md
```

## 核心设计原则

1. **领域可插拔** — 加新领域只需在 `domains/` 下新建文件夹，引擎代码不动
2. **采集全量入库** — 不做时间过滤，所有条目存入数据库
3. **LLM 只筛近期** — 只对最近 N 天的未评分条目跑 LLM（控制成本）
4. **展示按时间过滤** — 前端按用户选择的时间窗口过滤（24h/3d/7d/30d）
5. **宁缺毋滥** — 无日期的条目不入库，超过时效的不展示

## CLI 命令

```bash
# 采集（全量入库，无时间过滤）
python -m engine.cli -d elderly-care fetch

# 筛选（只处理最近 3 天未评分条目）
python -m engine.cli -d elderly-care filter

# 生成日报
python -m engine.cli -d elderly-care report

# 一键流水线
python -m engine.cli -d elderly-care pipe

# 启动 API 服务
python -m engine.cli -d elderly-care api
```

## 添加新领域

1. 创建 `domains/<name>/` 目录
2. 编写 `sources.yaml`（信源配置）
3. 编写 `categories.yaml`（分类体系）
4. 编写 `keywords.yaml`（关键词列表）
5. 编写 `scoring.md`（LLM 评分 prompt）
6. 编写 `pre_filter.md`（LLM 预筛 prompt）
7. 运行 `python -m engine.cli -d <name> pipe`

## 添加新信源

在 `domains/<name>/sources.yaml` 中添加：

```yaml
- id: new_source
  name: 新信源名称
  kind: rss  # rss / web / ageclub / searxng
  url: https://example.com/feed
  tier: T1   # T1 / T1.5 / T2
  lang: zh   # zh / en / ja
  keywords_filter: false  # true = 用关键词过滤
  tags: [标签1, 标签2]
```

## 信源类型

- **rss** — RSS/Atom 订阅，天然带日期
- **web** — 网页抓取，需要 CSS 选择器
- **ageclub** — AgeClub 专用，自动提取原始来源
- **searxng** — SearXNG 搜索，按关键词搜索

## API 端点

```
GET /api/items?domain=elderly-care&mode=selected&days=3
GET /api/categories?domain=elderly-care
GET /api/sources?domain=elderly-care
GET /api/stats?domain=elderly-care
GET /api/report/{date}?domain=elderly-care
GET /rss/curated?domain=elderly-care
GET /skill/{skill_name}/SKILL.md
```

## 开发规范

- 新增功能先在 `engine/` 下实现，再在 `domains/` 配置
- LLM prompt 修改在 `scoring.md` 和 `pre_filter.md` 中
- 前端模板在 `domains/<name>/web/index.html`
- 每次改动后跑一次 `python -m engine.cli -d <name> pipe` 验证

## 常见任务

**测试单个信源：**
```bash
python3 -c "
from engine.fetcher.rss_fetcher import fetch_rss
from engine.models import SourceDef, SourceKind
s = SourceDef(id='test', name='test', kind=SourceKind.RSS, url='https://example.com/feed', lang='zh')
items = fetch_rss(s)
print(f'{len(items)} items')
"
```

**查看数据库内容：**
```bash
python3 -c "
from engine.store import Store
s = Store()
rows = s.conn.execute('SELECT source_id, COUNT(*) FROM raw_items GROUP BY source_id').fetchall()
for r in rows:
    print(f'{r[0]}: {r[1]}')
"
```

**重新生成 dashboard：**
```bash
python3 -c "
import json
from engine.store import Store
from pathlib import Path
s = Store()
items = s.get_selected('elderly-care', take=500, min_score=0)
# ... 生成 HTML
"
```
