import json
with open("coverage.json") as f:
    data = json.load(f)

# Show first 20 file paths
for i, f in enumerate(sorted(data["files"].keys())[:20]):
    s = data["files"][f]["summary"]
    print(f'{s["covered_lines"]:4d}/{s["num_statements"]:4d}  {f}')

# Find zero-coverage files
zero = [(f, data["files"][f]["summary"]) for f in data["files"] if data["files"][f]["summary"]["covered_lines"] == 0 and data["files"][f]["summary"]["num_statements"] > 3]
print(f"\nTotal zero-coverage files (>3 stmts): {len(zero)}")
zero.sort(key=lambda x: -x[1]["num_statements"])
for f, s in zero[:40]:
    print(f'  {s["num_statements"]:4d}  {f}')
