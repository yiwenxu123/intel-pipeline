# Intel Pipeline

可配置的行业情报引擎，支持多领域插拔。

## 支持领域

| 领域 | 代号 | 说明 |
|---|---|---|
| 银发产业 | `elderly-care` | 养老、大健康、银发经济 |
| 中非经贸 | `china-africa` | 中非贸易、投资、政策 |

## 快速开始

### macOS / Linux

```bash
# 克隆项目
git clone https://github.com/your-username/intel-pipeline.git
cd intel-pipeline

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -e .

# 配置
cp .env.example .env
# 编辑 .env，填入 API key

# 运行
python -m engine.cli -d elderly-care pipe
```

### Windows

```powershell
# 克隆项目
git clone https://github.com/your-username/intel-pipeline.git
cd intel-pipeline

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -e .

# 配置
copy .env.example .env
# 编辑 .env，填入 API key

# 运行
run.bat pipe
```

## 命令

```bash
# 采集（全量入库）
python -m engine.cli -d elderly-care fetch

# 筛选（最近 3 天未评分条目）
python -m engine.cli -d elderly-care filter

# 生成日报
python -m engine.cli -d elderly-care report

# 完整流水线
python -m engine.cli -d elderly-care pipe

# 启动 API
python -m engine.cli -d elderly-care api

# 生成 Dashboard
run.bat dashboard
```

## Agent 接入

```bash
# 安装 Skill
帮我安装这个 skill：/skill/elderly-care/SKILL.md

# RSS 订阅
/rss/curated?domain=elderly-care

# REST API
GET /api/items?domain=elderly-care&days=3
```

## 项目结构

```
intel-pipeline/
├── engine/              # 通用引擎
├── domains/             # 领域配置
├── skills/              # SKILL.md 文件
├── data/                # 运行时数据
├── scripts/             # 脚本
├── CLAUDE.md            # AI Agent 开发指南
├── .env.example         # 配置模板
├── run.bat              # Windows 启动脚本
└── pyproject.toml       # Python 项目配置
```

## 开发

```bash
# 用 Claude Code 开发
claude

# 用 OpenCode 开发
opencode

# 查看项目说明
cat CLAUDE.md
```
