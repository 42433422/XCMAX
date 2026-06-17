"""分析覆盖率差距，输出 Top 未覆盖模块。"""
import json
import sys

with open('coverage_full.json') as f:
    data = json.load(f)

files = data['files']
ranked = []
for name, info in files.items():
    s = info['summary']
    missing = s['missing_lines']
    total = s['num_statements']
    if total < 5:
        continue
    pct = s['percent_covered']
    ranked.append((name, total, missing, pct))

ranked.sort(key=lambda x: x[2], reverse=True)

print("{:<80} {:>6} {:>6} {:>6}".format("module", "total", "miss", "cov%"))
print("-" * 100)
for name, total, missing, pct in ranked[:50]:
    short = name.replace('app/', '')
    print("{:<80} {:>6} {:>6} {:>6.1f}".format(short, total, missing, pct))

print()
totals = data['totals']
print("TOTAL: lines={:.2f}% branches={:.2f}%".format(
    totals['percent_covered'],
    totals.get('percent_covered_branches', 0)
))
