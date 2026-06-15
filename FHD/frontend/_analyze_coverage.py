import json

with open('coverage/coverage-summary.json') as f:
    data = json.load(f)

total = data.get('total', {})
print('=== TOTAL COVERAGE ===')
print(f"Lines:      {total.get('lines', {}).get('pct', 0)}%")
print(f"Branches:   {total.get('branches', {}).get('pct', 0)}%")
print(f"Functions:  {total.get('functions', {}).get('pct', 0)}%")
print(f"Statements: {total.get('statements', {}).get('pct', 0)}%")
print()

files = []
for filepath, info in data.get('files', {}).items():
    if '/node_modules/' in filepath:
        continue
    fn_total = info.get('functions', {}).get('total', 0)
    fn_covered = info.get('functions', {}).get('covered', 0)
    fn_uncovered = fn_total - fn_covered
    fn_pct = info.get('functions', {}).get('pct', 0)
    if fn_uncovered > 0:
        files.append((filepath, fn_total, fn_covered, fn_uncovered, fn_pct))

files.sort(key=lambda x: x[3], reverse=True)
print('=== TOP 40 FILES BY UNCOVERED FUNCTIONS ===')
for f, total, covered, uncovered, pct in files[:40]:
    short = f.split('src/')[-1] if 'src/' in f else f.split('frontend/')[-1]
    print(f'{uncovered:>4} unc / {total:>4} tot ({pct:>5.1f}%) | {short}')

# Also compute total uncovered functions
total_fn = data['total']['functions']['total']
total_fn_covered = data['total']['functions']['covered']
total_fn_uncovered = total_fn - total_fn_covered
print(f"\nTotal functions: {total_fn}, Covered: {total_fn_covered}, Uncovered: {total_fn_uncovered}")
print(f"Need to cover ~{int(total_fn * 0.80) - total_fn_covered} more functions to reach 80%")
