#!/bin/bash
# 安装 macOS LaunchAgent：API + 调度器登录自启并保持运行
# 用法：./scripts/install-launchagent.sh [domain]  （默认 elderly-care，仅 API 领域）
#       ./scripts/install-launchagent.sh elderly-care --with-scheduler

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DOMAIN="${1:-elderly-care}"
WITH_SCHEDULER="${2:-}"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/data/logs"
AGENTS_DIR="$HOME/Library/LaunchAgents"
UID_NUM=$(id -u)

get_port() {
  case "$1" in
    china-africa) echo 8900 ;;
    elderly-care) echo 8901 ;;
    *) echo "" ;;
  esac
}

install_plist() {
  local label=$1
  local plist_path="$AGENTS_DIR/${label}.plist"
  # 先卸载旧实例，再加载新 plist（可重复执行）
  launchctl bootout "gui/${UID_NUM}/${label}" 2>/dev/null || true
  sleep 0.5
  if ! launchctl bootstrap "gui/${UID_NUM}" "$plist_path" 2>/dev/null; then
    # 已加载时 bootstrap 会失败，直接 kickstart 重载
    launchctl kickstart -k "gui/${UID_NUM}/${label}" 2>/dev/null || true
  fi
  launchctl enable "gui/${UID_NUM}/${label}" 2>/dev/null || true
}

PORT=$(get_port "$DOMAIN")
if [ -z "$PORT" ]; then
  echo "❌ 未知领域: $DOMAIN"
  exit 1
fi

if [ ! -f "$VENV_PYTHON" ]; then
  echo "❌ 找不到虚拟环境: $VENV_PYTHON"
  exit 1
fi

mkdir -p "$LOG_DIR" "$AGENTS_DIR"

API_LABEL="com.intel-pipeline.api.${DOMAIN}"
API_PLIST="$AGENTS_DIR/${API_LABEL}.plist"

cat > "$API_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${API_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${VENV_PYTHON}</string>
    <string>-m</string>
    <string>engine.cli</string>
    <string>-d</string>
    <string>${DOMAIN}</string>
    <string>api</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>INTEL_API_PORT</key>
    <string>${PORT}</string>
  </dict>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/api-${DOMAIN}.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/api-${DOMAIN}.log</string>
</dict>
</plist>
EOF

echo "📡 安装 API LaunchAgent ($DOMAIN)..."
install_plist "$API_LABEL"
echo "   ✅ $API_LABEL → http://localhost:${PORT}/?domain=${DOMAIN}"

# 调度器（默认一并安装；传 --api-only 则跳过）
if [ "$WITH_SCHEDULER" != "--api-only" ]; then
  SCHED_LABEL="com.intel-pipeline.scheduler"
  SCHED_PLIST="$AGENTS_DIR/${SCHED_LABEL}.plist"

  cat > "$SCHED_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${SCHED_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${VENV_PYTHON}</string>
    <string>${PROJECT_DIR}/scripts/scheduler.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/scheduler.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/scheduler.log</string>
</dict>
</plist>
EOF

  echo "⏰ 安装调度器 LaunchAgent..."
  install_plist "$SCHED_LABEL"
  echo "   ✅ $SCHED_LABEL"
fi

echo ""
echo "🎉 LaunchAgent 安装完成"
echo "   查看状态: ./scripts/status.sh"
echo ""
echo "卸载 API:"
echo "  launchctl bootout gui/${UID_NUM}/${API_LABEL} && rm -f \"$API_PLIST\""
echo "卸载调度器:"
echo "  launchctl bootout gui/${UID_NUM}/com.intel-pipeline.scheduler && rm -f \"$AGENTS_DIR/com.intel-pipeline.scheduler.plist\""
