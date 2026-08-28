@echo off
REM Intel Pipeline - Windows 定时任务安装脚本（完整版）
REM 2026-08-28 体检后重写：对齐部署机实际 7 个任务
REM Report 已移除 —— Daily pipe 已含日报，避免 01:00 双任务并发写库
REM API-Boot 需要管理员权限注册（SYSTEM 开机自启、免登录）；其余普通权限即可

set "PROJECT_DIR=C:\Users\yihong123\Projects\intel-pipeline"
set "RUN=%PROJECT_DIR%\run.bat"
set "API_BAT=%PROJECT_DIR%\scripts\win-api.bat"

echo 项目目录: %PROJECT_DIR%
echo.

REM ── 采集 / 筛选 ──
schtasks /create /tn "IntelPipeline-Fetch-00"   /sc daily /st 00:00 /tr "%RUN% fetch"  /f >nul && echo [OK] 每天 00:00 采集
schtasks /create /tn "IntelPipeline-Filter"     /sc daily /st 00:30 /tr "%RUN% filter" /f >nul && echo [OK] 每天 00:30 筛选
schtasks /create /tn "IntelPipeline-NoonFetch"  /sc daily /st 12:00 /tr "%RUN% noon"   /f >nul && echo [OK] 每天 12:00 午间采集
schtasks /create /tn "IntelPipeline-NoonFilter" /sc daily /st 12:30 /tr "%RUN% filter" /f >nul && echo [OK] 每天 12:30 午间筛选

REM ── 完整流水线（含日报 / 进化后处理）──
schtasks /create /tn "IntelPipeline-Daily" /sc daily /st 01:00 /tr "%RUN% pipe" /f >nul && echo [OK] 每天 01:00 完整流水线

REM ── 进化分析（每周一 02:00）──
schtasks /create /tn "IntelPipeline-Evolve" /sc weekly /d MON /st 02:00 /tr "%RUN% evolve" /f >nul && echo [OK] 每周一 02:00 进化分析

REM ── API 守护（开机自启 SYSTEM 免登录；重定向在 win-api.bat 内部，勿在 Action 里写重定向）──
schtasks /create /tn "IntelPipeline-API-Boot" /sc onstart /delay 0000:15 /ru SYSTEM /tr "%API_BAT%" /f >nul && echo [OK] 开机自启 API（SYSTEM，延迟 15s，日志 data\api.log） || echo [失败] 注册 SYSTEM 任务需以管理员运行

REM ── 防火墙放行 8900（需管理员；绑定 0.0.0.0 供跨机访问）──
netsh advfirewall firewall add rule name="IntelPipeline-API-8900" dir=in action=allow protocol=TCP localport=8900 >nul 2>&1 && echo [OK] 防火墙已放行 TCP 8900 || echo [跳过] 防火墙规则需以管理员运行

echo.
echo 已注册 7 个任务：
schtasks /query /fo table | findstr /i IntelPipeline
echo.
pause
