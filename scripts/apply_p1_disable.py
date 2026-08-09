"""P1: 在 Windows 版 sources.yaml 上禁用 3 个死 WeRSS 源（幂等）"""
import re
from pathlib import Path

path = Path("domains/elderly-care/sources.yaml")
t = path.read_text(encoding="utf-8")

# 要禁用的源 + 注释
targets = {
    "wx_changhuxqgc": "2026-08-09 自动降级：WeRSS 抓取停更（6/27 后无新文），待 WeRSS 恢复后重新启用",
    "wx_zgylbx": "2026-08-09 自动降级：WeRSS 抓取停更（6/27 后无新文），待 WeRSS 恢复后重新启用",
    "wx_zglnjy": "2026-08-09 自动降级：WeRSS 抓取停更（6/27 后无新文），待 WeRSS 恢复后重新启用",
}

changed = []
for src_id, note in targets.items():
    # 找到该源的块（- id: xxx 到下一个 - id: 或结尾）
    pat = re.compile(r"(- id: " + src_id + r"\n.*?)(?=\n- id: |\Z)", re.S)
    m = pat.search(t)
    if not m:
        print(f"[SKIP] {src_id} 未找到")
        continue
    block = m.group(1)
    if "enabled: false" in block:
        print(f"[SKIP] {src_id} 已禁用")
        continue
    # 在块末尾 tags 行之后加 enabled: false
    if block.rstrip().endswith("tags:"):
        # tags 是列表形式，找到最后一个 tag 项后插入
        lines = block.rstrip("\n").split("\n")
        # 找最后一个非空行，在其后插入
        idx = len(lines)
        while idx > 0 and not lines[idx-1].strip():
            idx -= 1
        lines.insert(idx, f"    enabled: false  # {note}")
        new_block = "\n".join(lines) + "\n"
    else:
        # tags 是 flow 形式，直接在块末尾追加
        indent = "    "
        new_block = block.rstrip("\n") + "\n" + indent + f"enabled: false  # {note}\n"
    t = t[:m.start(1)] + new_block + t[m.end(1):]
    changed.append(src_id)

if changed:
    path.write_text(t, encoding="utf-8")
    print(f"[OK] 已禁用: {', '.join(changed)}")
else:
    print("[OK] 无需修改")
