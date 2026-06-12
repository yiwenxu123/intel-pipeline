@echo off
REM Intel Pipeline - Windows 定时任务安装脚本
REM 以管理员身份运行

echo ========================================
echo Intel Pipeline 定时任务安装
echo ========================================
echo.

set "PROJECT_DIR=C:\Users\yihong123\Projects\intel-pipeline"
set "SCRIPT=%PROJECT_DIR%\run.bat"

echo 项目目录: %PROJECT_DIR%
echo.

REM ── 1. 中午 12:00 采集 ──
schtasks /create /tn "IntelPipeline-NoonFetch" /sc daily /st 12:00 ^
    /tr "%SCRIPT% noon" /f /ru SYSTEM
echo [OK] 12:00 采集

REM ── 2. 午夜 00:00 采集 ──
schtasks /create /tn "IntelPipeline-MidnightFetch" /sc daily /st 00:00 ^
    /tr "%SCRIPT% fetch" /f /ru SYSTEM
echo [OK] 00:00 采集

REM ── 3. 00:30 筛选（凌晨采集后） ──
schtasks /create /tn "IntelPipeline-MidnightFilter" /sc daily /st 00:30 ^
    /tr "%SCRIPT% filter" /f /ru SYSTEM
echo [OK] 00:30 筛选

REM ── 4. 01:00 生成日报 ──
schtasks /create /tn "IntelPipeline-DailyReport" /sc daily /st 01:00 ^
    /tr "%SCRIPT% report" /f /ru SYSTEM
echo [OK] 01:00 日报

REM ── 5. 登录后自动启动 API ──
schtasks /create /tn "IntelPipeline-API-Login" /sc onlogon /delay 0000:02 ^
    /tr "%SCRIPT% api" /f /ru yihong123
echo [OK] API 登录自启

echo.
echo ========================================
echo 所有定时任务已注册
echo 查看状态: schtasks /query /tn "IntelPipeline-*"
echo ========================================

pause
