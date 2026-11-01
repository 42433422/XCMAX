#!/usr/bin/env python3
"""Fixed incident readback; no arguments, remote writes, or command execution."""
import json
import os
from pathlib import Path
import stat
import sys
import time

TARGET = Path('/var/www/update/releases/builds/1.0.0.7/9a7e4cc0f4fbfe07d083d9807eb0f857072e9f4d/server/fhd-full-1.0.0.7-9a7e4cc0f4fb.tar.gz')
IO_KEYS = {'rchar', 'wchar', 'read_bytes', 'write_bytes'}

def snapshot():
    files = []
    for label, path in [('partial', Path(str(TARGET) + '.part')), ('final', TARGET)]:
        row = {'target': label}
        try:
            info = path.lstat()
            row.update(size=info.st_size, mtime_ns=info.st_mtime_ns,
                       regular=stat.S_ISREG(info.st_mode), symlink=stat.S_ISLNK(info.st_mode))
        except OSError as error:
            row['errno'] = error.errno
        files.append(row)
    processes = []
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    ticks = os.sysconf('SC_CLK_TCK')
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            name = (entry / 'comm').read_text().strip()
            if name not in {'rsync', 'sshd', 'sshd-session'}:
                continue
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            row = dict(pid=int(entry.name), ppid=int(fields[1]), comm=name,
                       state=fields[0], elapsed_s=round(uptime - int(fields[19]) / ticks, 1))
            try:
                row['io'] = {k: int(v.strip()) for k, v in
                             (line.split(':', 1) for line in (entry / 'io').read_text().splitlines())
                             if k in IO_KEYS}
            except OSError as error:
                row['io_errno'] = error.errno
            processes.append(row)
        except (OSError, ValueError, IndexError):
            continue  # Process may exit while read; never reveal exception paths/content.
    return dict(timestamp_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                expected_bytes=30816636, files=files, processes=processes)

def main():
    if len(sys.argv) != 1:
        raise SystemExit('No arguments accepted')
    print(json.dumps(snapshot(), sort_keys=True), flush=True)
    time.sleep(30)
    print(json.dumps(snapshot(), sort_keys=True), flush=True)

if __name__ == '__main__':
    main()
