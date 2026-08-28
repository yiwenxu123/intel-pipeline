@echo off
REM Intel Pipeline - API 守护启动脚本（供计划任务调用）
REM 由计划任务 IntelPipeline-API-Login（登录触发）调用。
REM 重定向在脚本内部完成：不要在 schtasks Action 里写 "cmd /c ... >> log"，
REM 引号嵌套会导致任务退出码 255 且日志文件都不建立。
cd /d "%~dp0.."
if not exist data mkdir data
call run.bat api >> data\api.log 2>&1
