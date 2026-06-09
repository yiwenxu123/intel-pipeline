#!/bin/bash
# Intel Pipeline — 一键启动所有服务
# 用法：./scripts/start.sh [domain]  （不传参则启动所有领域）

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
PID_DIR="$PROJECT_DIR/data/pids"
LOG_DIR="$PROJECT_DIR/data/logs"

# 领域 → 端口映射
get_port() {
  case "$1" in
    china-africa) echo 8900 ;;
    elderly-care) echo 8901 ;;
    *) echo "" ;;
  esac
}

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

mkdir -p "$PID_DIR" "$LOG_DIR"

# 检查 venv
if [ ! -f "$VENV_PYTHON" ]; then
  echo -e "${RED}❌ 找不到 Python 虚拟环境: $VENV_PYTHON${NC}"
  echo "请先运行: python3 -m venv .venv && source .venv/bin/activate && pip install -e ."
  exit 1
fi

# 启动单个领域 API
start_domain() {
  local domain=$1
  local port=$(get_port "$domain")
  local pid_file="$PID_DIR/api-${domain}.pid"
  local log_file="$LOG_DIR/api-${domain}.log"

  # 检查是否已运行
  if [ -f "$pid_file" ]; then
    local old_pid=$(cat "$pid_file")
    if kill -0 "$old_pid" 2>/dev/null; then
      echo -e "${YELLOW}⚠️  $domain API 已在运行 (PID $old_pid, 端口 $port)${NC}"
      return 0
    fi
    rm -f "$pid_file"
  fi

  # 也检查端口是否被占用
  if lsof -i:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    local busy_pid=$(lsof -i:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)
    echo -e "${YELLOW}⚠️  端口 $port 已被占用 (PID $busy_pid)，跳过 $domain${NC}"
    return 0
  fi

  echo -n "  启动 $domain (端口 $port)... "
  cd "$PROJECT_DIR"
  INTEL_API_PORT="$port" nohup "$VENV_PYTHON" -m engine.cli -d "$domain" api \
    > "$log_file" 2>&1 &
  local pid=$!
  echo "$pid" > "$pid_file"

  # 等待启动
  sleep 2
  if kill -0 "$pid" 2>/dev/null; then
    echo -e "${GREEN}✅ PID $pid${NC}"
  else
    echo -e "${RED}❌ 启动失败，查看日志: $log_file${NC}"
    rm -f "$pid_file"
    return 1
  fi
}

# 启动调度器
start_scheduler() {
  local pid_file="$PID_DIR/scheduler.pid"
  local log_file="$LOG_DIR/scheduler.log"

  if [ -f "$pid_file" ]; then
    local old_pid=$(cat "$pid_file")
    if kill -0 "$old_pid" 2>/dev/null; then
      echo -e "${YELLOW}⚠️  调度器已在运行 (PID $old_pid)${NC}"
      return 0
    fi
    rm -f "$pid_file"
  fi

  echo -n "  启动调度器... "
  cd "$PROJECT_DIR"
  nohup "$VENV_PYTHON" scripts/scheduler.py \
    > "$log_file" 2>&1 &
  local pid=$!
  echo "$pid" > "$pid_file"

  sleep 1
  if kill -0 "$pid" 2>/dev/null; then
    echo -e "${GREEN}✅ PID $pid${NC}"
  else
    echo -e "${RED}❌ 启动失败，查看日志: $log_file${NC}"
    rm -f "$pid_file"
    return 1
  fi
}

# ── 主流程 ──

echo "🚀 Intel Pipeline 启动"
echo ""

# 确定要启动的领域
if [ -n "$1" ]; then
  domains=("$1")
else
  domains=()
  for d in "$PROJECT_DIR"/domains/*/; do
    name=$(basename "$d")
    domains+=("$name")
  done
fi

echo "📡 启动 API 服务："
for domain in "${domains[@]}"; do
  port=$(get_port "$domain")
  if [ -n "$port" ]; then
    start_domain "$domain"
  else
    echo -e "  ${YELLOW}⏭️  $domain — 未配置端口，跳过${NC}"
  fi
done

echo ""
echo "⏰ 启动调度器："
start_scheduler

echo ""
echo "🎉 启动完成！"
echo ""
echo "访问地址："
for domain in "${domains[@]}"; do
  port=$(get_port "$domain")
  if [ -n "$port" ]; then
    echo "  📊 $domain → http://localhost:$port/?domain=$domain"
  fi
done
echo ""
echo "管理命令："
echo "  ./scripts/status.sh  — 查看状态"
echo "  ./scripts/stop.sh    — 停止所有服务"
