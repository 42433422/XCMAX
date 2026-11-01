"""Fixed read-only failed-startup observation; raw journal never leaves this process."""
import json
import re
import subprocess

SERVICE = 'fhd-full.service'
EXCEPTIONS = frozenset(('ModuleNotFoundError', 'ImportError', 'SyntaxError', 'IndentationError', 'NameError', 'AttributeError', 'TypeError', 'ValueError', 'RuntimeError', 'PermissionError', 'FileNotFoundError', 'OSError', 'KeyError', 'AssertionError', 'OperationalError'))

def summarize(raw):
    types, modules, frames = set(), set(), set()
    for line in raw.splitlines():
        match = re.search(r'\b([A-Za-z]+Error):', line)
        if match and match[1] in EXCEPTIONS:
            types.add(match[1])
        match = re.search(r"ModuleNotFoundError: No module named '([A-Za-z_][A-Za-z0-9_.]{0,120})'", line)
        if match:
            modules.add(match[1])
        match = re.search(r'\s*File "(/opt/fhd-full/(?:app|XCAGI|xcagi_common|packages)/[A-Za-z0-9_./-]+\.py)", line ([0-9]{1,7}), in [A-Za-z0-9_<>]+', line)
        if match and '..' not in match[1]:
            frames.add((match[1], int(match[2])))
    return {'exception_types': sorted(types), 'missing_modules': sorted(modules), 'source_frames': [{'path': p, 'line': n} for p, n in sorted(frames)][:30]}

def read(args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=15, check=False)
    return result.returncode, result.stdout

def main():
    code, raw = read(['journalctl', '-u', SERVICE, '--since', '2026-11-01 08:39:20 UTC', '--until', '2026-11-01 08:44:20 UTC', '-n', '5000', '--no-pager', '-o', 'json'])
    size_ok = len(raw.encode('utf-8')) <= 4 * 1024 * 1024
    messages = []
    invalid = 0
    if size_ok:
        for row in raw.splitlines():
            try:
                message = json.loads(row).get('MESSAGE')
                if isinstance(message, str):
                    messages.append(message)
                else:
                    invalid += 1
            except (ValueError, AttributeError):
                invalid += 1
    output = summarize('\n'.join(messages))
    output['journal_read_ok'] = code == 0
    output['journal_entries_examined'] = len(messages)
    output['journal_invalid_entries'] = invalid
    output['journal_size_limit_exceeded'] = not size_ok
    output['journal_entry_limit_reached'] = len(messages) >= 5000
    del raw, messages
    code, raw = read(['systemctl', 'show', SERVICE, '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result', '-p', 'ExecMainStatus', '-p', 'ExecStart', '-p', 'StandardOutput', '-p', 'StandardError'])
    states = {'ActiveState': {'active', 'inactive', 'activating', 'deactivating', 'failed'}, 'SubState': {'running', 'dead', 'failed', 'start', 'auto-restart', 'exited'}, 'Result': {'success', 'exit-code', 'signal', 'timeout', 'core-dump', 'start-limit-hit', 'resources'}}
    output['service_read_ok'] = code == 0
    for line in raw.splitlines():
        key, _, value = line.partition('=')
        if key in states:
            output[key] = value if value in states[key] else 'unrecognized'
        elif key == 'ExecMainStatus' and re.fullmatch(r'[0-9]{1,4}', value):
            output[key] = int(value)
        elif key in ('StandardOutput', 'StandardError'):
            kind = value.split(':', 1)[0]
            output[key] = kind if kind in ('journal', 'journal-or-kmsg', 'kmsg', 'null', 'inherit', 'file', 'append', 'truncate', 'tty', 'socket') else 'unrecognized'
        elif key == 'ExecStart':
            match = re.search(r'(?:^|[ {;])path=(/(?:usr/(?:local/)?bin|opt/fhd-full/\.venv/bin)/python[0-9.]*)\s*;', value)
            output['python_executable'] = match[1] if match else 'not-a-recognized-python-executable'
    print(json.dumps(output, sort_keys=True))

if __name__ == '__main__':
    try:
        main()
    except (OSError, subprocess.TimeoutExpired):
        print('{"diagnostic_read_failed": true}')
        raise SystemExit(1)
