#!/bin/bash
# pull-intel-data.sh — 从 Windows 部署机拉取 intel-data.json 与每日日报 md 到本机
#
# 数据流：Windows run.bat pipe/filter 末尾 export-intel 产出 data/intel-data.json，
#         report 阶段产出 data/reports/YYYY-MM-DD-elderly-care.md
#         → 本脚本 scp 拉回 Mac →
#           ① intel-data.json：content-ops-agent 的 IntelPipelineSource 经 fs.watch + cron 幂等摄入 signals
#           ② reports/*.md：晚 23:30 kb-evening 的 sync-intel-reports.sh 同步进 Obsidian 知识库
#
# 用法: pull-intel-data.sh
# 调度: launchd com.radar.intel-pull（每日 01:40 / 13:00，覆盖 pipe 01:00 与午间 filter 12:30 批次）
# 依赖: ~/.ssh/config 的 my-windows 别名（免密）
#
# 2026-09-12 修复：reports 此前无人拉取（仅拉 intel-data.json），Obsidian 知识库断供 18 天。

set -u

WINDOWS_HOST="${INTEL_WINDOWS_HOST:-my-windows}"
WINDOWS_PATH="${INTEL_WINDOWS_REMOTE_PATH:-C:/Users/yihong123/Projects/intel-pipeline/data/intel-data.json}"
REPORTS_REMOTE="${INTEL_REPORTS_REMOTE:-C:/Users/yihong123/Projects/intel-pipeline/data/reports}"
REPORT_DAYS="${INTEL_REPORT_DAYS:-7}"
LOCAL_DIR="${INTEL_LOCAL_DIR:-$HOME/Projects/ai-agents/intel-pipeline/data}"
LOG="${INTEL_PULL_LOG:-$LOCAL_DIR/pull-intel.log}"

mkdir -p "$LOCAL_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

pull_json() {
  local TMP="$LOCAL_DIR/.intel-data.json.tmp.$$"
  local FINAL="$LOCAL_DIR/intel-data.json"
  for attempt in 1 2; do
    if scp -q -o ConnectTimeout=15 -o BatchMode=yes "$WINDOWS_HOST:$WINDOWS_PATH" "$TMP" 2>>"$LOG"; then
      # 校验 JSON 合法（防止拉到半截/坏文件喂给消费方）
      if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$TMP" >/dev/null 2>&1; then
        if [ -f "$FINAL" ] && cmp -s "$TMP" "$FINAL"; then
          rm -f "$TMP"
          log "内容无变化，跳过"
        else
          mv "$TMP" "$FINAL"
          local COUNT
          COUNT=$(python3 -c "import json;print(json.load(open('$FINAL')).get('count',0))" 2>/dev/null || echo '?')
          log "拉取成功：$COUNT 条"
        fi
        return 0
      fi
      log "第 ${attempt} 次：拉取的文件不是合法 JSON，丢弃"
      rm -f "$TMP"
    else
      log "第 ${attempt} 次：scp 失败（Windows 不可达或远端文件未生成）"
    fi
    sleep 20
  done
  return 1
}

# 拉取近 N 天日报 md（只拉主文件；「待审」副本含中文名，跨机 scp 编码不稳且非知识库必需）
pull_reports() {
  local reports_local="$LOCAL_DIR/reports"
  mkdir -p "$reports_local"
  local pulled=0 d f
  for i in 0 1 2 3 4 5 6; do
    d=$(date -v-${i}d +%F)
    f="$reports_local/$d-elderly-care.md"
    [ -s "$f" ] && continue
    if scp -q -o ConnectTimeout=15 -o BatchMode=yes \
        "$WINDOWS_HOST:$REPORTS_REMOTE/$d-elderly-care.md" "$f" 2>>"$LOG"; then
      pulled=$((pulled + 1))
      log "拉取日报：$d-elderly-care.md"
    fi
  done
  [ "$pulled" -gt 0 ] && log "日报拉取完成：$pulled 份"
  return 0
}

pull_json
json_rc=$?
pull_reports
exit $json_rc
