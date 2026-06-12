@echo off
REM Intel Pipeline - 状态检查

echo ========================================
echo Intel Pipeline 状态检查
echo ========================================
echo.

REM 检查定时任务
echo [定时任务]
schtasks /query /tn "IntelPipeline-*" /v /fo list 2>nul | findstr /i "TaskName Status Next Run Time"
if %errorlevel% neq 0 (
    echo   未找到定时任务，请先运行 install-scheduler.bat
)
echo.

REM 检查 API 状态
echo [API 服务]
curl -s http://127.0.0.1:8900/health >nul 2>&1
if %errorlevel% equ 0 (
    curl -s http://127.0.0.1:8900/health
    echo.
) else (
    echo   ❌ API 未运行
)
echo.

REM 检查数据库
echo [数据库]
cd /d "%~dp0.."
.venv\Scripts\python -c "from engine.store import Store; s=Store(); raw=s.conn.execute('SELECT COUNT(*) FROM raw_items').fetchone()[0]; scored=s.conn.execute(\"SELECT COUNT(*) FROM scored_items WHERE domain='elderly-care'\").fetchone()[0]; sel=s.conn.execute(\"SELECT COUNT(*) FROM scored_items WHERE domain='elderly-care' AND score>=6.0\").fetchone()[0]; print(f'  原始: {raw} 条'); print(f'  已评分: {scored} 条'); print(f'  精选: {sel} 条')"
echo.

echo ========================================
