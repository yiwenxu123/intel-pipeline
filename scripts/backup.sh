#!/bin/bash
# Intel Pipeline — 备份数据库与领域配置

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_ROOT="$PROJECT_DIR/data/backups"
STAMP=$(date +%Y%m%d-%H%M%S)
DEST="$BACKUP_ROOT/$STAMP"

mkdir -p "$DEST"

echo "📦 备份到 $DEST"

for db in "$PROJECT_DIR"/data/intel-*.db; do
  [ -f "$db" ] || continue
  cp "$db" "$DEST/"
  echo "  ✓ $(basename "$db")"
done

if [ -d "$PROJECT_DIR/domains" ]; then
  cp -R "$PROJECT_DIR/domains" "$DEST/domains"
  echo "  ✓ domains/"
fi

echo "✅ 备份完成"
echo "恢复示例："
echo "  ./scripts/stop.sh"
echo "  cp $DEST/intel-elderly-care.db $PROJECT_DIR/data/"
echo "  ./scripts/start.sh elderly-care"
