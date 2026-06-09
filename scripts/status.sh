#!/bin/bash
# Intel Pipeline — 查看服务状态

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="$PROJECT_DIR/data/pids"
LOG_DIR="$PROJECT_DIR/data/logs"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "📊 Intel Pipeline 状态"
echo ""

running=0
total=0

for pid_file in "$PID_DIR"/*.pid; do
  [ -f "$pid_file" ] || continue
  name=$(basename "$pid_file" .pid)
  pid=$(cat "$pid_file")
  total=$((total + 1))

  if kill -0 "$pid" 2>/dev/null; then
    # 获取进程运行时间
    if [[ "$OSTYPE" == "darwin"* ]]; then
      elapsed=$(ps -p "$pid" -o etime= 2>/dev/null | xargs)
      mem=$(ps -p "$pid" -o rss= 2>/dev/null | xargs)
      if [ -n "$mem" ]; then
        mem_mb=$((mem / 1024))
        mem_info="${mem_mb}MB"
      else
        mem_info=""
      fi
    else
      elapsed=$(ps -p "$pid" -o etime= 2>/dev/null | xargs)
      mem_info=""
    fi

    # 检查端口
    port_info=""
    if [[ "$name" == api-* ]]; then
      domain=${name#api-}
      case "$domain" in
        china-africa) port=8900 ;;
        elderly-care) port=8901 ;;
        *) port="" ;;
      esac
      if [ -n "$port" ]; then
        if lsof -i:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
          port_info="端口 $port ✓"
        else
          port_info="端口 $port ✗"
        fi
      fi
    fi

    echo -e "  ${GREEN}●${NC} $name"
    echo -e "    PID $pid | 运行 $elapsed | $mem_info | $port_info"
    running=$((running + 1))
  else
    echo -e "  ${RED}●${NC} $name"
    echo -e "    PID $pid — ${RED}已退出${NC}"
    rm -f "$pid_file"
  fi
done

if [ "$total" -eq 0 ]; then
  echo -e "  ${YELLOW}没有已注册的服务${NC}"
  echo ""
  echo "  运行 ./scripts/start.sh 启动服务"
else
  echo ""
  echo "  运行中: $running / $total"
fi

# 显示最近日志
if [ -d "$LOG_DIR" ] && [ "$(ls -A "$LOG_DIR" 2>/dev/null)" ]; then
  echo ""
  echo "📝 最近日志（最后 3 行）："
  for log_file in "$LOG_DIR"/*.log; do
    [ -f "$log_file" ] || continue
    name=$(basename "$log_file" .log)
    echo -e "  ${YELLOW}$name:${NC}"
    tail -3 "$log_file" 2>/dev/null | sed 's/^/    /'
  done
fi
