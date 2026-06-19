import json
with open('coverage/coverage-final.json') as f:
    data = json.load(f)
for key, val in data.items():
    if 'runOnboardingTour' in key or 'kittenDatasetParser' in key:
        fname = key.split('/')[-1]
        s = val['statementMap']
        cnt_s = val['s']
        total_s = len(cnt_s)
        covered_s = sum(1 for v in cnt_s.values() if v > 0)
        b = val['branchMap']
        cnt_b = val['b']
        total_b = sum(len(v) for v in cnt_b.values())
        covered_b = sum(sum(1 for x in v if x > 0) for v in cnt_b.values())
        f_map = val['fnMap']
        cnt_f = val['f']
        total_f = len(cnt_f)
        covered_f = sum(1 for v in cnt_f.values() if v > 0)
        print(f'{fname}:')
        print(f'  Statements: {covered_s}/{total_s} = {covered_s/total_s*100:.2f}%')
        print(f'  Branches:   {covered_b}/{total_b} = {covered_b/total_b*100:.2f}%')
        print(f'  Functions:  {covered_f}/{total_f} = {covered_f/total_f*100:.2f}%')
        for bid, hits in cnt_b.items():
            for i, h in enumerate(hits):
                if h == 0:
                    loc = b[bid]
                    print(f'  uncovered branch line {loc["line"]} type={loc["type"]}')
