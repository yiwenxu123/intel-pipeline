import re

fpath = "/opt/services/hermes/hermes-data/skills/content-theme-finder/scripts/collector.py"
content = open(fpath, "r", encoding="utf-8").read()

# Find and insert after AIHOT block
lines = content.split("\n")
insert_idx = None
for i, line in enumerate(lines):
    if "AIHOT 未安装" in line and "跳过" in line:
        for j in range(i + 1, min(i + 5, len(lines))):
            if lines[j].strip() and "logger.info" in lines[j] and "原始信号" in lines[j]:
                insert_idx = j
                break
        if insert_idx:
            break

if insert_idx:
    new_block = '''
        if "intel_pipeline" in sources:
            print("   🔗 Intel Pipeline 情报...")
            try:
                result = self._get_intel_pipeline()
                logger.info(f"[IntelPipeline] 采集到 {len(result)} 条信号")
                signals.extend(result)
            except Exception as e:
                logger.warning(f"[IntelPipeline] 采集异常: {e}")
                print(f"   ⚠️ Intel Pipeline 采集异常: {e}")

'''
    lines.insert(insert_idx, new_block)
    content = "\n".join(lines)
    open(fpath, "w", encoding="utf-8").write(content)
    print(f"OK: inserted at line {insert_idx}")
else:
    print("FAIL: insert position not found")
    for i, line in enumerate(lines):
        if "AIHOT" in line or "总计" in line:
            print(f"  {i}: {line.strip()[:60]}")
