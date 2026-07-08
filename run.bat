@echo off
REM Intel Pipeline - Windows 启动脚本
REM 用法: run.bat [fetch|filter|report|pipe|api|dashboard|all]

cd /d "%~dp0"

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

if "%CMD%"=="" set CMD=help

if "%CMD%"=="fetch" (
    echo [%DATE% %TIME%] 采集 %DOMAIN% ...
    python -m engine.cli -d %DOMAIN% fetch --max-workers 4
    echo [%DATE% %TIME%] 采集完成
    goto :end
)

if "%CMD%"=="filter" (
    echo [%DATE% %TIME%] 筛选 %DOMAIN% ...
    python -m engine.cli -d %DOMAIN% filter
    echo [%DATE% %TIME%] 筛选完成
    goto :end
)

if "%CMD%"=="report" (
    echo [%DATE% %TIME%] 生成日报 %DOMAIN% ...
    python -m engine.cli -d %DOMAIN% report
    echo [%DATE% %TIME%] 日报生成完成
    goto :end
)

if "%CMD%"=="pipe" (
    echo [%DATE% %TIME%] 完整流水线 %DOMAIN% ...
    python -m engine.cli -d %DOMAIN% pipe
    echo [%DATE% %TIME%] 流水线完成
    goto :end
)

if "%CMD%"=="nightly" (
    REM 夜间流水线：采集 + 筛选 + 日报
    echo [%DATE% %TIME%] === 开始夜间流水线 ===
    python -m engine.cli -d %DOMAIN% fetch --max-workers 4
    python -m engine.cli -d %DOMAIN% filter
    python -m engine.cli -d %DOMAIN% report
    echo [%DATE% %TIME%] === 夜间流水线完成 ===
    goto :end
)

if "%CMD%"=="noon" (
    REM 中午采集：只采集，不筛选
    echo [%DATE% %TIME%] === 中午采集 ===
    python -m engine.cli -d %DOMAIN% fetch --max-workers 4
    echo [%DATE% %TIME%] === 中午采集完成 ===
    goto :end
)

if "%CMD%"=="api" (
    echo [%DATE% %TIME%] 启动 API 服务...
    python -c "from engine.output.api import app; import uvicorn; uvicorn.run(app, host='0.0.0.0', port=8900)"
    goto :end
)

if "%CMD%"=="evolve" (
    echo [%DATE% %TIME%] 进化分析 %DOMAIN% ...
    python -m engine.cli -d %DOMAIN% evolve all
    echo [%DATE% %TIME%] 进化分析完成
    goto :end
)

if "%CMD%"=="dashboard" (
    echo [%DATE% %TIME%] 生成面板...
    python -c "import json; from engine.store import Store; from pathlib import Path; s=Store(); items=s.get_selected('%DOMAIN%', take=500, min_score=0); stats=s.get_stats('%DOMAIN%'); s.close(); template=Path('domains/elderly-care/web/index.html').read_text(); data={'items': items, 'stats': stats, 'domain_name': '银发产业情报'}; Path('data/dashboard-elderly-care.html').write_text(template[:template.find('<body')] + '\\n<script>window.__DATA=' + json.dumps(data, ensure_ascii=False, default=str) + '</script>\\n' + template[template.find('<body'):]); print('Dashboard 已生成: data/dashboard-elderly-care.html')"
    goto :end
)

if "%CMD%"=="help" (
    echo 用法: run.bat [命令]
    echo.
    echo   fetch     - 采集信源
    echo   filter    - 筛选评分
    echo   report    - 生成日报
    echo   pipe      - 完整流水线
    echo   nightly   - 夜间流水线（0点后：采集+筛选+日报）
    echo   noon      - 中午采集（仅采集）
    echo   api       - 启动 API 服务
    echo   dashboard - 生成面板
    goto :end
)

:end
