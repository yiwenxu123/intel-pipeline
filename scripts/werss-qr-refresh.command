#!/bin/bash
# WeRSS 授权二维码 · Mac 侧一键刷新
#
# 用法：Finder 里双击本文件（或在终端运行）。
#      它会删掉旧码 → 生成新码 → 自动用“预览”打开放大版 → 盯着扫码结果。
#
# 为什么要“一键 + 自动弹窗”：微信二维码两侧都是 ~5 分钟就失效
#   · 微信侧：二维码图片本身过期
#   · 程序侧：driver/wx.py 等待 `timeout=5*60*1000` 后关闭浏览器
# 过了窗口再扫，微信就会提示「系统错误，请稍后再试」。
# 所以：弹出图片后请立刻扫，别切去做别的事。

set -uo pipefail

WIN_HOST="yihong123@10.207.251.86"
WIN_QR_WIN='%USERPROFILE%\werss-test\we-mp-rss\static\wx_qrcode.png'
WIN_LOCK_WIN='%USERPROFILE%\werss-test\we-mp-rss\data\lock.lock'
API="http://10.207.251.86:8001/api/v1/wx"
OUT_IMG="$HOME/.cache"                     # 临时目录
mkdir -p "$OUT_IMG"

PY=/Users/yiwenxu123/.workbuddy/binaries/python/versions/3.13.12/bin/python3
[ -x "$PY" ] || PY=python3

bar() { printf '===============================================\n'; }

bar
echo " WeRSS 二维码刷新"
bar

# --- 0. 服务存活检查
code=$(curl --noproxy '*' -s -o /dev/null -w '%{http_code}' --max-time 10 "$API/auth/login" -X POST \
         -H 'Content-Type: application/x-www-form-urlencoded' -d 'username=&password=' 2>/dev/null)
if [ "$code" = "000" ]; then
  echo " ✗ 连不上 WeRSS（$API）"
  echo "   请在 Windows 上确认服务与计划任务 WeRSS-Verify 正在运行。"
  read -r -p " 按回车退出..." _
  exit 1
fi

# --- 1. 删旧码（不删则 /qr/code 直接返回旧文件，不会重新生成）
echo " [1/5] 清除旧二维码..."
ssh -o ConnectTimeout=15 -o StrictHostKeyChecking=no "$WIN_HOST" \
  "del /q \"$WIN_QR_WIN\" 2>nul & del /q \"$WIN_LOCK_WIN\" 2>nul & echo  done" 2>/dev/null | tail -1

# --- 2. 登录
echo " [2/5] 登录 WeRSS API..."
TOKEN=$(curl --noproxy '*' -s --max-time 25 -X POST \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=werss_verify&password=Verify@2026' "$API/auth/login" \
  | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])' 2>/dev/null)
if [ -z "${TOKEN:-}" ]; then
  echo " ✗ 登录失败"
  read -r -p " 按回车退出..." _
  exit 1
fi

# --- 3. 触发新码
echo " [3/5] 触发二维码生成（浏览器渲染约 10-20 秒）..."
curl --noproxy '*' -s --max-time 90 -H "Authorization: Bearer $TOKEN" \
  "$API/auth/qr/code" >/dev/null 2>&1

SZ=0
for _ in $(seq 1 24); do
  sleep 5
  SZ=$(ssh -o ConnectTimeout=10 "$WIN_HOST" \
    'powershell -NoProfile -Command "$p=Join-Path $env:USERPROFILE \"werss-test\we-mp-rss\static\wx_qrcode.png\"; if (Test-Path $p) { (Get-Item $p).Length } else { 0 }"' \
    2>/dev/null | tr -d '\r' | tail -1)
  [ "${SZ:-0}" -gt 1000 ] 2>/dev/null && break
done

if [ "${SZ:-0}" -le 1000 ] 2>/dev/null; then
  echo " ✗ 60 秒内没生成二维码。"
  echo "   Windows 上查看 %USERPROFILE%\\werss-test\\run.out.log 的尾部。"
  read -r -p " 按回车退出..." _
  exit 1
fi

# --- 4. 取图 + 放大 + 弹出
echo " [4/5] 取图并弹出..."
curl --noproxy '*' -s --max-time 20 -o "$OUT_IMG/werss_qr_raw.png" \
  "http://10.207.251.86:8001/static/wx_qrcode.png"
sips -z 480 480 "$OUT_IMG/werss_qr_raw.png" --out "$OUT_IMG/werss_qr_big.png" >/dev/null 2>&1
open "$OUT_IMG/werss_qr_big.png"

echo ""
echo " >>> 二维码已弹出，请立刻用微信扫（有效期约 5 分钟）<<<"
echo ""

# --- 5. 盯结果（最多 4 分钟）
echo " [5/5] 等待扫码结果..."
OK=0
for i in $(seq 1 80); do
  sleep 3
  S=$(curl --noproxy '*' -s --max-time 10 -H "Authorization: Bearer $TOKEN" "$API/auth/qr/status" 2>/dev/null)
  case "$S" in
    *'"login_status":true'*) OK=1; break ;;
  esac
  [ $((i % 10)) -eq 0 ] && echo "    ... 已等待 $((i * 3)) 秒"
done

echo ""
bar
if [ "$OK" = "1" ]; then
  echo " ✓ 扫码成功，微信授权已通过"
  bar
  echo " 告诉助手一声，它会立刻跑单号抓取测试。"
else
  echo " ✗ 未检测到登录成功"
  bar
  echo " 如果手机上微信报了错，多半是二维码/会话已过期。"
  echo " 再双击一次本文件，出码后马上扫。"
fi
echo ""
read -r -p " 按回车关闭窗口..." _
