"""One-use, hash-bound repair application for XCMAX draft PR 2761.

This helper is removed from the resulting tree. It never pushes, merges a PR,
changes repository protection, or executes product code with write credentials.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
TRANSPORT = ROOT / '.github/audit-remediation-2761'
EXPECTED_PATCH = '14ac697aef41dd68c7312ccb1fc8be297a7b0a1141dbfc90358e30065b3febf3'
BRANCH = 'fix/audit-a01-a14-20261029'


def run(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    print(result.stdout, end='')
    if result.returncode:
        print(result.stderr, file=sys.stderr, end='')
        raise SystemExit(result.returncode)
    return result.stdout.strip()


def main() -> None:
    if os.environ.get('GITHUB_HEAD_REF') != BRANCH:
        raise SystemExit('Refusing any branch except the authorized remediation branch')
    expected_head = os.environ['AUDIT_EVENT_HEAD']
    if run('git', 'rev-parse', 'HEAD') != expected_head:
        raise SystemExit('Checkout identity mismatch')
    if run('git', 'status', '--porcelain'):
        raise SystemExit('Checkout must start clean')
    manifest = json.loads((TRANSPORT / 'manifest.json').read_text())
    compressed = b''.join((TRANSPORT / f'{i:02d}.part').read_bytes() for i in range(9))
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
        patch = source.read(2 * 1024 * 1024 + 1)
    if len(patch) != 114305 or hashlib.sha256(patch).hexdigest() != EXPECTED_PATCH:
        raise SystemExit('Patch integrity mismatch')
    patch_path = ROOT / '.git/audit-remediation.patch'
    patch_path.write_bytes(patch)
    selected = tuple('--include=' + path for path in manifest)
    applied = subprocess.run(
        ('git', 'apply', '--3way', '--index', *selected, str(patch_path)),
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    print(applied.stdout, end='')
    print(applied.stderr, file=sys.stderr, end='')
    if applied.returncode:
        # Only the independently developed A07 regression file may conflict.
        # Preserve its original assertions in the separate length-zero module.
        conflict = 'FHD/tests/test_etl_validation_value_fidelity.py'
        unmerged = run('git', 'diff', '--name-only', '--diff-filter=U').splitlines()
        if unmerged != [conflict]:
            raise SystemExit(f'Unexpected reviewed patch conflicts: {unmerged}')
        stage3 = run('git', 'rev-parse', ':3:' + conflict)
        if stage3 != manifest[conflict]:
            raise SystemExit('Reviewed patch target hash mismatch for A07 conflict')
        run('git', 'checkout', '--theirs', '--', conflict)
        run('git', 'add', '--', conflict)
    if run('git', 'ls-files', '-u'):
        raise SystemExit('Unresolved merge stages remain')

    changed = set(run('git', 'diff', '--cached', '--name-only', '-z').split('\0')) - {''}
    if changed != set(manifest):
        raise SystemExit('Unexpected staged paths')
    for path, expected in manifest.items():
        if run('git', 'hash-object', '--', path) != expected:
            raise SystemExit(f'Repaired file mismatch: {path}')
    run('git', 'diff', '--cached', '--check')
    run('git', 'commit', '-m', 'fix(audit): make payment fulfillment atomic and verify WeChat notifications',
        '-m', 'Also complete ETL false-value handling and restore tested outbox/Retort/tool-runner compatibility. '
        '65 focused Python business tests pass with warnings as errors; Java notification tests await CI. '
        'Remaining audit findings are not claimed resolved.')
    # Synchronize only the real product mainline. No other unfinished branch is merged.
    run('git', 'merge', '--no-edit', 'refs/remotes/origin/main')
    main_sha = run('git', 'rev-parse', 'refs/remotes/origin/main')
    log = ROOT / 'FHD/CHANGELOG.md'
    text = log.read_text(encoding='utf-8')
    marker = '## Unreleased\n'
    lines = text.splitlines()
    if len(lines) < 3 or not lines[0].startswith('# ') or lines[1] or lines[2] != '## Unreleased':
        raise SystemExit('Expected current Unreleased section at changelog start')
    entry = (
        '\n- 审计整改候选（PR #2761）：充值履约改为与余额同一事务的唯一凭证，订单文件原子写入；'
        '客服发送先领取、核对有效回执，结果未知时停止自动重发；ETL保留0和False；'
        '任务重放不重复派发，未执行的验证工具不再算通过。微信支付回调新增原始通知验签候选。\n'
        '- 本批覆盖A02/A03/A05/A06/A07/A12/A13的候选修复，仍待完整CI与目标环境验收；'
        'A01/A04/A08/A09/A10/A11/A14不得据此关闭。'
        '历史付款和消息/任务结果未知时须先核对数据库流水、渠道回执和实际副作用，禁止盲目重放；'
        'Java密钥/证书配置与轮换见既有支付服务README。\n'
    )
    log.write_text(text.replace(marker, marker + entry, 1), encoding='utf-8')
    # Remove exactly the transient transport/helper files created by this task.
    # The one-use snapshot workflow must also leave the reviewed branch;
    # otherwise its next synchronization would invoke the deleted helper.
    run('git', 'rm', '-r', '--', '.github/audit-remediation-2761',
        '.github/workflows/fhd-audit-remediation-snapshot.yml',
        'FHD/.github/workflows/audit-remediation-snapshot.yml')
    run(sys.executable, '成都修茈科技有限公司/scripts/build_capability_center.py')
    run('git', 'add', '--', 'FHD/CHANGELOG.md',
        '成都修茈科技有限公司/capabilities', '成都修茈科技有限公司/data/capabilities.json')
    net = subprocess.run(
        [sys.executable, 'scripts/dev/check_net_deletion.py', '--json'],
        cwd=ROOT / 'FHD', text=True, capture_output=True, check=False,
    )
    if net.returncode not in (0, 1):
        raise SystemExit(net.stderr)
    counts = json.loads(net.stdout)
    print(net.stdout)
    reason = (
        f"PR#2761：用户要求审计问题全量整改；本批新增事务履约、回调验签、并发领取与负向回归，"
        f"维护行数{counts['baseline']}→{counts['current']}（净增{counts['delta']}）。"
        '按仓库显式例外提交评审，不删除无关代码凑数，不修改测试或安全门槛；剩余审计项未关闭。'
    )
    baseline = ROOT / 'FHD/metrics/line_baseline.json'
    if counts['delta'] > 0:
        run(sys.executable, 'scripts/dev/check_net_deletion.py', '--update', '--force', '--reason',
            reason, cwd=ROOT / 'FHD')
        run('git', 'add', '--', 'FHD/metrics/line_baseline.json')
    run('git', 'diff', '--cached', '--check')
    run('git', 'commit', '-m', 'docs(audit): record candidate scope and remove temporary verification transport')
    run(sys.executable, 'scripts/dev/push_preflight.py', '--fix', '--base', 'origin/main', cwd=ROOT / 'FHD')
    if run('git', 'status', '--porcelain'):
        raise SystemExit('Preflight changed files; review is required before pushing')
    counter = runpy.run_path(str(ROOT / 'FHD/scripts/dev/check_net_deletion.py'))
    temporary_workflows = ('FHD/.github/workflows/audit-remediation-snapshot.yml',
                           '.github/workflows/fhd-audit-remediation-snapshot.yml')
    temporary_lines = sum(counter['_count_lines'](ROOT / path) for path in temporary_workflows
                          if counter['_is_counted'](path) and not counter['_has_generated_banner'](ROOT / path))
    receipt = {'temporary_workflow_counted_lines': temporary_lines, 'event_head': expected_head, 'main_sha': main_sha,
               'final_head': run('git', 'rev-parse', 'HEAD'),
               'final_tree': run('git', 'rev-parse', 'HEAD^{tree}'),
               'patch_sha256': EXPECTED_PATCH, 'net_deletion': counts,
               'baseline': json.loads(baseline.read_text()),
               'formal_audit_status': 'UNRATED', 'preflight': 'passed'}
    (ROOT / '.git/audit-remediation-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
