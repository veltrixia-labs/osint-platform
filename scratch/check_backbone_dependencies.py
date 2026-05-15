from pathlib import Path
import json
from collections import defaultdict

BASE = Path("data/backbone")

FILES = [
    "energy_master_stakeholders_v1.json",
    "market_master_stakeholders_v1.json",
    "crypto_master_stakeholders_v1.json",
    "ai_tech_master_stakeholders_v1.json",
    "defense_master_stakeholders_v1.json",
    "trade_master_stakeholders_v1.json",
]

all_nodes = {}
nodes_by_file = {}

for filename in FILES:
    path = BASE / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    nodes_by_file[filename] = data

    for node in data:
        all_nodes[node["name"]] = {
            "file": filename,
            "node": node,
        }

def loose_find(target: str):
    target_l = target.lower()
    for name, info in all_nodes.items():
        name_l = name.lower()
        if name_l == target_l:
            return name, info
        if target_l in name_l or name_l in target_l:
            return name, info
    return None, None

total_deps = 0
matched_deps = 0
missing = []

for filename, nodes in nodes_by_file.items():
    for node in nodes:
        for dep in node.get("top_dependencies", []):
            total_deps += 1
            target = dep.get("target", "")

            matched_name, matched_info = loose_find(target)

            if matched_info:
                matched_deps += 1
            else:
                missing.append({
                    "source_file": filename,
                    "source_node": node.get("name"),
                    "target": target,
                    "type": dep.get("type"),
                    "weight": dep.get("weight"),
                })

print("=" * 80)
print("BACKBONE DEPENDENCY CHECK")
print("=" * 80)
print(f"Total dependencies: {total_deps}")
print(f"Matched dependencies: {matched_deps}")
print(f"Missing dependencies: {len(missing)}")
print(f"Coverage: {matched_deps / total_deps * 100:.1f}%")
print()

missing_by_file = defaultdict(int)
for m in missing:
    missing_by_file[m["source_file"]] += 1

print("Missing by file:")
for file, count in sorted(missing_by_file.items(), key=lambda x: x[1], reverse=True):
    print(f"  {file}: {count}")

print()
print("First 50 missing dependencies:")
print("-" * 80)

for m in missing[:50]:
    print(f"[{m['source_file']}]")
    print(f"  source: {m['source_node']}")
    print(f"  target: {m['target']}")
    print(f"  type:   {m['type']}")
    print(f"  weight: {m['weight']}")
    print()