#!/bin/bash
# pull-intel-data.sh — 从 Windows 部署机拉取 intel-data.json 到本机
#
# 数据流：Windows run.bat pipe/filter 末尾 export-intel 产出 data/intel-data.json
#         → 本脚本 scp 拉回 Mac → content-ops-agent 的 IntelPipelineSource
#           经 fs.watch + cron 幂等摄入 signals 集合。
#
# 用法: pull-intel-data.sh
# 调度: launchd com.radar.intel-pull（每日 01:40 / 13:00，覆盖 pipe 01:00 与午间 filter 12:30 批次）
# 依赖: ~/.ssh/config 的 my-windows 别名（免密）

set -u

WINDOWS_HOST="${INTEL_WINDOWS_HOST:-my-windows}"
WINDOWS_PATH="${INTEL_WINDOWS_REMOTE_PATH:-C:/Users/yihong123/Projects/intel-pipeline/data/intel-data.json}"
LOCAL_DIR="${INTEL_LOCAL_DIR:-$HOME/Projects/ai-agents/intel-pipeline/data}"
LOG="${INTEL_PULL_LOG:-$LOCAL_DIR/pull-intel.log}"

mkdir -p "$LOCAL_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

TMP="$LOCAL_DIR/.intel-data.json.tmp.$$"
FINAL="$LOCAL_DIR/intel-data.json"

for attempt in 1 2; do
  if scp -q -o ConnectTimeout=15 -o BatchMode=yes "$WINDOWS_HOST:$WINDOWS_PATH" "$TMP" 2>>"$LOG"; then
    # 校验 JSON 合法（防止拉到半截/坏文件喂给消费方）
    if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$TMP" >/dev/null 2>&1; then
      if [ -f "$FINAL" ] && cmp -s "$TMP" "$FINAL"; then
        rm -f "$TMP"
        log "内容无变化，跳过"
      else
        mv "$TMP" "$FINAL"
        COUNT=$(python3 -c "import json;print(json.load(open('$FINAL')).get('count',0))" 2>/dev/null || echo '?')
        log "拉取成功：$COUNT 条"
      fi
      exit 0
    fi
    log "第 ${attempt} 次：拉取的文件不是合法 JSON，丢弃"
    rm -f "$TMP"
  else
    log "第 ${attempt} 次：scp 失败（Windows 不可达或远端文件未生成）"
  fi
  sleep 20
done
log "两次尝试均失败，等待下次调度"
exit 1
