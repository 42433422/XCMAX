"""Fixed read-only failed-startup observation; raw journal never leaves this process."""
import json
import re
import subprocess
import shlex
import os

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


# Exact startup guards: factory.py:97, lifespan.py:348/351, mod_startup.py:81.
EVENT_PATTERNS = {
    'exec_failed': r'Failed at step EXEC|Failed to execute|Failed to locate executable|can.t open file',
    'working_directory_failed': r'Failed at step CHDIR|Changing to the requested working directory failed',
    'permission_denied': r'Permission denied',
    'bind_failed': r'address already in use|error while attempting to bind|Address family not supported',
    'asgi_import_failed': r'Error loading ASGI app|Could not import module',
    'start_limit': r'Start request repeated too quickly|start-limit-hit',
    'signal_exit': r'code=killed|code=dumped|Killed process|oom-kill',
    'main_process_exited': r'Main process exited',
    'restart_scheduled': r'Scheduled restart job',
    'started_process': r'Started server process',
    'startup_waiting': r'Waiting for application startup',
    'startup_complete': r'Application startup complete',
    'startup_failed': r'Application startup failed',
    'server_listening': r'Uvicorn running on',
    'shutdown': r'Shutting down|Application shutdown complete',
    'production_key_guard': r'SECRET_KEY must be set in production',
    'database_init_failed': r'数据库初始化失败',
    'mod_background_failed': r'background load_all_mods failed',
    'guarded_runtime_failed': r'guarded (?:catalog|parent|application|identity|workers).*?(?:differs|changed|requires|unavailable|not drained)',
}

def record_summary(records):
    events, metadata, message_types, listeners = {}, {}, {}, []
    for record in records:
        message = record.get('MESSAGE')
        kind = 'str' if isinstance(message, str) else 'bytes_array' if isinstance(message, list) else 'other'
        message_types[kind] = message_types.get(kind, 0) + 1
        if kind == 'bytes_array':
            try:
                message = bytes(message).decode('utf-8', errors='replace')
            except (ValueError, TypeError):
                message = ''
        if not isinstance(message, str):
            message = ''
        timestamp = str(record.get('__REALTIME_TIMESTAMP', ''))
        timestamp = int(timestamp) if re.fullmatch(r'[0-9]{15,17}', timestamp) else None
        for name, pattern in EVENT_PATTERNS.items():
            if re.search(pattern, message, re.IGNORECASE):
                event = events.setdefault(name, {'count': 0, 'first_us': timestamp, 'last_us': timestamp})
                event['count'] += 1
                event['last_us'] = timestamp
        endpoint = re.search(r'Uvicorn running on (https?)://(\[[0-9a-fA-F:]+\]|[A-Za-z0-9_.-]+):([0-9]{1,5})(?:[/\s]|$)', message)
        if endpoint and 1 <= int(endpoint[3]) <= 65535:
            host = endpoint[2].lower()
            category = 'loopback' if host in ('127.0.0.1', 'localhost', '[::1]') else 'wildcard' if host in ('0.0.0.0', '[::]') else 'other'
            value = {'host_category': category, 'port': int(endpoint[3]), 'time_us': timestamp}
            if value not in listeners:
                listeners.append(value)
        for field in ('MESSAGE_ID', 'EXIT_CODE', 'EXIT_STATUS', '_COMM'):
            value = record.get(field)
            allowed = isinstance(value, str) and (
                (field == 'MESSAGE_ID' and re.fullmatch(r'[0-9a-f]{32}', value)) or
                (field == 'EXIT_STATUS' and re.fullmatch(r'[0-9]{1,4}', value)) or
                (field == 'EXIT_CODE' and value in ('exited', 'killed', 'dumped')) or
                (field == '_COMM' and value in ('systemd', 'python', 'python3', 'uvicorn', 'gunicorn')))
            if allowed:
                key = field + ':' + value
                metadata[key] = metadata.get(key, 0) + 1
        match = re.search(r'code=(exited|killed|dumped), status=([0-9]{1,4})(?:/|\b)', message)
        if match:
            key = 'process_exit:' + match[1] + ':' + match[2]
            metadata[key] = metadata.get(key, 0) + 1
    return {'event_categories': events, 'structured_counts': metadata, 'message_types': message_types, 'listening_endpoints': listeners[:20]}

def read(args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=15, check=False)
    return result.returncode, result.stdout


PORT_KEYS = ('FASTAPI_PORT', 'XCAGI_API_PORT', 'PORT')
CONFIG_PATHS = (
    '/opt/fhd-full/XCAGI/.env',
    '/opt/fhd-full/.env',
    '/opt/fhd-full-backups/pre-20261101-163908/XCAGI/.env',
    '/opt/fhd-full-backups/pre-20261101-163908/.env',
)

def port_value(value):
    value = value.strip().strip('"').strip("'")
    return int(value) if re.fullmatch(r'[0-9]{1,5}', value) and 1 <= int(value) <= 65535 else 'invalid'

def allowed_port_lines(lines):
    result = dict.fromkeys(PORT_KEYS, 'absent')
    for line in lines:
        match = re.match(r'^\s*(?:export\s+)?(FASTAPI_PORT|XCAGI_API_PORT|PORT)\s*=(.*)$', line)
        if match:
            result[match[1]] = port_value(match[2])
    return result

def config_summary():
    output = {}
    for path in CONFIG_PATHS:
        item = {'exists': os.path.lexists(path), 'symlink': os.path.islink(path)}
        if item['exists'] and not item['symlink']:
            try:
                with open(path, encoding='utf-8', errors='replace') as stream:
                    item['ports'] = allowed_port_lines(stream)
            except OSError:
                item['read_failed'] = True
        output[path] = item
    code, raw = read(['systemctl', 'show', SERVICE, '-p', 'Environment', '--value'])
    ports = dict.fromkeys(PORT_KEYS, 'absent')
    try:
        lexer = shlex.shlex(raw, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ''
        for assignment in lexer:
            key, _, value = assignment.partition('=')
            if key in PORT_KEYS:
                ports[key] = port_value(value)
    except ValueError:
        output['systemd_environment_parse_failed'] = True
    del raw
    output['systemd_ports'] = ports
    output['systemd_environment_read_ok'] = code == 0
    return output

def main():
    code, raw = read(['journalctl', '-u', SERVICE, '--since', '2026-11-01 08:39:20 UTC', '--until', '2026-11-01 08:44:20 UTC', '-n', '5000', '--no-pager', '-o', 'json'])
    size_ok = len(raw.encode('utf-8')) <= 4 * 1024 * 1024
    messages = []
    records = []
    invalid = 0
    if size_ok:
        for row in raw.splitlines():
            try:
                record = json.loads(row)
                records.append(record)
                message = record.get('MESSAGE')
                if isinstance(message, str):
                    messages.append(message)
                else:
                    invalid += 1
            except (ValueError, AttributeError):
                invalid += 1
    output = summarize('\n'.join(messages))
    output.update(record_summary(records))
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
            output['known_entry_paths'] = [p for p in ('/opt/fhd-full/XCAGI/run.py', '/opt/fhd-full/XCAGI/run_fastapi.py', '/opt/fhd-full/run.py') if p in value]
            port_arg = re.search(r'(?:^|\s)--port(?:=|\s+)([0-9]{1,5})(?:\s|;|$)', value)
            output['cli_port'] = port_value(port_arg[1]) if port_arg else 'absent'
    output['port_config_sources'] = config_summary()
    print(json.dumps(output, sort_keys=True))

if __name__ == '__main__':
    try:
        main()
    except (OSError, subprocess.TimeoutExpired):
        print('{"diagnostic_read_failed": true}')
        raise SystemExit(1)
