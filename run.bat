@echo off
REM Intel Pipeline - Windows 启动脚本
REM 用法: run.bat [fetch|filter|report|pipe|nightly|noon|evolve|api|dashboard]

cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\activate.bat" (
    echo First run: python -m venv .venv ^&^& .venv\Scripts\activate ^&^& pip install -e .
    exit /b 1
)

call .venv\Scripts\activate.bat >nul 2>&1
set DOMAIN=elderly-care
set CMD=%1

if "%CMD%"=="" set CMD=help

if "%CMD%"=="fetch" (
    python -m engine.cli -d %DOMAIN% fetch --max-workers 4
    goto :end
)
if "%CMD%"=="filter" (
    python -m engine.cli -d %DOMAIN% filter
    python -m engine.cli -d %DOMAIN% export-intel
    goto :end
)
if "%CMD%"=="report" (
    python -m engine.cli -d %DOMAIN% report
    goto :end
)
if "%CMD%"=="pipe" (
    python -m engine.cli -d %DOMAIN% pipe
    python -m engine.cli -d %DOMAIN% export-intel
    goto :end
)
if "%CMD%"=="nightly" (
    python -m engine.cli -d %DOMAIN% fetch --max-workers 4
    python -m engine.cli -d %DOMAIN% filter
    python -m engine.cli -d %DOMAIN% report
    python -m engine.cli -d %DOMAIN% export-intel
    goto :end
)
if "%CMD%"=="noon" (
    python -m engine.cli -d %DOMAIN% fetch --max-workers 4
    goto :end
)
if "%CMD%"=="evolve" (
    python -m engine.cli -d %DOMAIN% evolve all
    goto :end
)
if "%CMD%"=="api" (
    python -c "from engine.output.api import app; import uvicorn; uvicorn.run(app, host='0.0.0.0', port=8900)"
    goto :end
)
if "%CMD%"=="dashboard" (
    python -c "import json;from engine.store import Store;from pathlib import Path;s=Store();items=s.get_selected('%DOMAIN%',take=500,min_score=0);stats=s.get_stats('%DOMAIN%');s.close();t=Path('domains/%DOMAIN%/web/index.html').read_text(encoding='utf-8');d={'items':items,'stats':stats,'domain_name':'银发产业情报'};js='window.__DATA='+json.dumps(d,ensure_ascii=False,default=str);t=t.replace('<body','<script>'+js+'</script>\n<body',1);Path('data/dashboard-%DOMAIN%.html').write_text(t,encoding='utf-8');print('OK')"
    goto :end
)

echo Commands: fetch ^| filter ^| report ^| pipe ^| nightly ^| noon ^| evolve ^| api ^| dashboard ^| export-intel
:end
