#!/bin/bash
# Intel Pipeline — 停止所有服务

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="$PROJECT_DIR/data/pids"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "🛑 Intel Pipeline 停止"
echo ""

stopped=0

for pid_file in "$PID_DIR"/*.pid; do
  [ -f "$pid_file" ] || continue
  name=$(basename "$pid_file" .pid)
  pid=$(cat "$pid_file")

  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null
    # 等待进程退出（最多 5 秒）
    for i in $(seq 1 10); do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.5
    done
    # 如果还在运行，强制杀
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null
      echo -e "  ${YELLOW}⚡ $name (PID $pid) — 强制终止${NC}"
    else
      echo -e "  ${GREEN}✅ $name (PID $pid) — 已停止${NC}"
    fi
    stopped=$((stopped + 1))
  else
    echo -e "  ${YELLOW}⏭️  $name (PID $pid) — 未运行${NC}"
  fi
  rm -f "$pid_file"
done

# 也清理可能残留的端口占用
for port in 8900 8901; do
  pid=$(lsof -i:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null
    echo -e "  ${YELLOW}🧹 端口 $port 残留进程 (PID $pid) — 已清理${NC}"
  fi
done

# 停止 LaunchAgent（若已安装）
if [[ "$OSTYPE" == "darwin"* ]]; then
  UID_NUM=$(id -u)
  for label in com.intel-pipeline.scheduler com.intel-pipeline.api.elderly-care com.intel-pipeline.api.china-africa; do
    if launchctl print "gui/${UID_NUM}/${label}" >/dev/null 2>&1; then
      launchctl bootout "gui/${UID_NUM}/${label}" 2>/dev/null && \
        echo -e "  ${GREEN}✅ launchd/$label — 已停止${NC}" && stopped=$((stopped + 1))
    fi
  done
fi

if [ "$stopped" -eq 0 ]; then
  echo -e "${YELLOW}没有运行中的服务${NC}"
else
  echo ""
  echo -e "${GREEN}已停止 $stopped 个服务${NC}"
fi
