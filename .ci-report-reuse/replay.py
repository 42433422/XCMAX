"""Paired historical-artifact replay: never presented as new CI acceptance."""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path.cwd()
out = Path(os.environ['RUNNER_TEMP']) / 'evidence'
old = Path(os.environ['RUNNER_TEMP']) / 'baseline/scripts/ci/backend_shard_aggregate.py'
new = root / 'scripts/ci/backend_shard_aggregate.py'
first = json.loads((root / 'replay-shards/backend-shard-1-1/full.json').read_text())
assert first['GITHUB_RUN_ID'] == '39703375132'
assert first['BACKEND_SOURCE_SHA'] == '0ae939a358e0a1a8a253e0e68220bf5e70dd498e'
# GitHub Git-commit read independently verified the tested merge source has this tree.
assert subprocess.check_output(['git','rev-parse','4a80c983b179c876bf43e9689910dcb9b218e6c2^{tree}'],text=True).strip() == '100e545110df01146655b8bcc46e6bde70f65b70'
env = dict(os.environ, **{k: first[k] for k in ('GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','BACKEND_SOURCE_SHA')})
env.update(BACKEND_SHARD_TOTAL='8', BACKEND_TIMINGS_FILE='metrics/backend_test_timings.json', PYTHONPATH=str(root), XCAGI_SKIP_LEGACY_COMPAT_ROUTES='1')
records=[]
reference=None
reference_xml=None
for index, (label, script) in enumerate([('baseline',old),('candidate',new),('candidate',new),('baseline',old)]):
    timing=out/f'replay-{index}-{label}.json'
    with (out/f'replay-{index}-{label}.log').open('w') as log:
        subprocess.run([sys.executable,str(script),'replay-shards','--artifact-prefix','backend-shard-1-','--timing-path',str(timing)],env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=240)
    reports=[]
    for name in ('coverage.json','coverage-behavior.json'):
        data=json.loads(Path(name).read_text())
        reports.append({key:value for key,value in data.items() if key!='meta'})
    xml=ET.parse('coverage.xml').getroot()
    xml.attrib.pop('timestamp',None)
    normalized_xml=ET.tostring(xml)
    if reference is None:
        reference=reports
        reference_xml=normalized_xml
    assert reports==reference, f'JSON semantics changed: {label}'
    assert normalized_xml==reference_xml, f'XML semantics changed: {label}'
    record=json.loads(timing.read_text())
    assert record['status']=='success'
    if label=='candidate':
        assert record['behavior_report_reused'] is True
        assert [s['name'] for s in record['stages']][-2:]==['ratchet-full','ratchet-behavior']
    records.append({'variant':label,'seconds':record['total_seconds']})
(out/'replay-summary.json').write_text(json.dumps({'source_run':39703375132,'source_sha':first['BACKEND_SOURCE_SHA'],'scope':'same-run, same-source historical-evidence replay; not new full CI','order':'ABBA','records':records,'json_equal':True,'xml_equal':True,'both_ratchets_executed':True},indent=2))
print(json.dumps(records,indent=2))
