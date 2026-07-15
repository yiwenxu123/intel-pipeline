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

REM ── 每日凌晨 1:00 完整流水线 ──
schtasks /create /tn "IntelPipeline-Daily" /sc daily /st 01:00 ^
    /tr "%SCRIPT% pipe" /f /ru SYSTEM
echo [OK] 每天 01:00 完整流水线（pipe）

echo.
echo ========================================
echo 定时任务已注册
echo 每天 01:00 自动执行：采集 → 筛选 → 日报 → 编辑审阅版
echo 查看状态: schtasks /query /tn "IntelPipeline-Daily"
echo ========================================

pause