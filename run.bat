@echo off
REM Intel Pipeline - Windows 启动脚本
REM 用法: run.bat [fetch|filter|pipe|api|dashboard]

cd /d "%~dp0"

REM 检查虚拟环境
if not exist ".venv\Scripts\activate.bat" (
    echo 虚拟环境不存在，请先运行:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -e .
    exit /b 1
)

call .venv\Scripts\activate.bat

set DOMAIN=elderly-care
set CMD=%1

if "%CMD%"=="" set CMD=dashboard

if "%CMD%"=="fetch" (
    echo [采集] 开始采集 %DOMAIN% ...
    python -m engine.cli -d %DOMAIN% fetch
    goto :end
)

if "%CMD%"=="filter" (
    echo [筛选] 开始筛选 %DOMAIN% ...
    python -m engine.cli -d %DOMAIN% filter
    goto :end
)

if "%CMD%"=="pipe" (
    echo [流水线] 执行完整流水线 %DOMAIN% ...
    python -m engine.cli -d %DOMAIN% pipe
    goto :end
)

if "%CMD%"=="api" (
    echo [API] 启动 API 服务...
    python -m engine.cli -d %DOMAIN% api
    goto :end
)

if "%CMD%"=="dashboard" (
    echo [Dashboard] 生成面板...
    python -c "import json; from engine.store import Store; from pathlib import Path; s=Store(); items=s.get_selected('%DOMAIN%', take=500, min_score=0); stats=s.get_stats('%DOMAIN%'); s.close(); template=Path('domains/%DOMAIN%/web/index.html').read_text(); data={'items': items, 'stats': stats, 'domain_name': '银发产业情报'}; html=template.replace('<body', f'<script>window.__DATA={json.dumps(data, ensure_ascii=False, default=str)};</script>\n<body', 1); Path('data/dashboard-%DOMAIN%.html').write_text(html); print(f'Dashboard: {len(items)} items')"
    echo 已生成: data\dashboard-%DOMAIN%.html
    start "" "data\dashboard-%DOMAIN%.html"
    goto :end
)

echo 用法: run.bat [fetch^|filter^|pipe^|api^|dashboard]
echo   fetch     - 采集信源数据
echo   filter    - LLM 筛选评分
echo   pipe      - 完整流水线
echo   api       - 启动 API 服务
echo   dashboard - 生成并打开面板

:end
