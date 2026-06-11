[根目录](../CLAUDE.md) > **domains**

# domains — 领域配置层

## 模块职责

通过 `domains/<name>/` 目录注入领域知识，引擎代码零修改即可支持新领域。`engine/domain.py` 的 `DomainConfig` 统一加载。

## 必需文件清单

| 文件 | 用途 | 必填 |
|---|---|---|
| `sources.yaml` | 信源定义（id, name, kind, url, tier, type, lang...） | ✅ |
| `categories.yaml` | 分类体系 + `freshness_days`（API 时间窗口） | ✅ |
| `keywords.yaml` | 关键词列表（`keywords_filter: true` 的信源用） | 推荐 |
| `scoring.md` | LLM 评分 system prompt | ✅ |
| `pre_filter.md` | LLM 预筛 prompt（当前主路径未使用） | ✅ |
| `daily_report.md` | 自定义日报模板 | 可选 |
| `web/index.html` | 领域专属前端 | **未实现** — 实际 Dashboard 在 `engine/output/templates/dashboard.html` |

## 当前领域

| 领域 | 目录 | 信源数 | 分类数 | 说明 |
|---|---|---|---|---|
| 银发产业 | `elderly-care/` | 54 | 7 | 养老、银发经济、智慧养老 |
| 中非经贸 | `china-africa/` | 21 | 8 | 贸易、投资、外交、风险 |

## 加载流程

```python
load_domain(name) → DomainConfig
  .sources          # list[SourceDef]
  .categories       # dict from YAML
  .category_freshness  # {cat_id: days}
  .keywords         # list[str]
  .scoring_prompt   # scoring.md 全文
  .pre_filter_prompt
```

## 添加新领域

1. 创建 `domains/<new-name>/` 并复制上述必需文件
2. 运行 `python -m engine.cli -d <new-name> fetch`
3. 可选：在 `skills/<new-name>/SKILL.md` 添加 Agent Skill

## 测试与质量

- `tests/test_domain.py` — 临时目录 fixture 验证加载逻辑
- **缺口**：无针对真实 `elderly-care`/`china-africa` yaml 内容的 schema 校验

## 相关文件清单

```
domains/
├── elderly-care/   → [CLAUDE.md](./elderly-care/CLAUDE.md)
└── china-africa/   → [CLAUDE.md](./china-africa/CLAUDE.md)
```

## 常见修改场景

| 场景 | 修改位置 |
|---|---|
| 加信源 | `domains/<name>/sources.yaml` |
| 调分类时间窗口 | `categories.yaml` 的 `freshness_days` |
| 改 LLM 评分标准 | `scoring.md` |
| 关键词过滤列表 | `keywords.yaml`（evolution 可自动追加） |
| 新增领域 | 复制 `elderly-care/` 目录结构 |

## 变更记录 (Changelog)

- **2026-06-11**：修正信源/分类计数；china-africa 已具备 keywords.yaml 与 freshness_days
- **2026-06-10**：init-architect 初始化；标注 web/index.html 缺口
