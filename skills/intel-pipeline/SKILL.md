---
name: intel-pipeline
description: 银发产业情报引擎。当用户想了解养老、银发经济、大健康领域的最新情报时使用。
---

# Intel Pipeline Skill

当用户询问养老、银发经济、大健康相关情报时，使用此 Skill。

## 项目位置
`C:\Users\yihong123\Projects\intel-pipeline`

## 常用命令

### 采集最新情报
```powershell
cd C:\Users\yihong123\Projects\intel-pipeline
run.bat fetch
```

### 筛选评分
```powershell
cd C:\Users\yihong123\Projects\intel-pipeline
run.bat filter
```

### 生成日报
```powershell
cd C:\Users\yihong123\Projects\intel-pipeline
run.bat report
```

### 完整流水线
```powershell
cd C:\Users\yihong123\Projects\intel-pipeline
run.bat pipe
```

### 查看数据库内容
```powershell
cd C:\Users\yihong123\Projects\intel-pipeline
.venv\Scripts\python -c "from engine.store import Store; s=Store(); rows=s.conn.execute('SELECT COUNT(*) FROM raw_items').fetchall(); print(f'总条目: {rows[0][0]}')"
```

## 领域
- `elderly-care` - 银发产业
- `china-africa` - 中非经贸

## 信源
- RSS 订阅（养老公众号、国际媒体）
- 网页抓取（民政部、AgeClub 等）
- SearXNG 搜索
