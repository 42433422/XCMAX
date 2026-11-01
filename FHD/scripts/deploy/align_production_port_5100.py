"""Explicit protected production config action: one fixed port, no restart or deployment."""
import hashlib
import json
import fcntl
import sys
import subprocess
import pwd
import tarfile
import os
from pathlib import Path
import re
import stat
import tempfile

class Refused(Exception):
    pass


def aligned_bytes(data):
    if len(data) > 1024 * 1024:
        raise Refused('size_limit')
    assignments = list(re.finditer(rb'(?m)^[ \t]*(?:export[ \t]+)?FASTAPI_PORT[ \t]*=.*$', data))
    if len(assignments) != 1:
        raise Refused('assignment_count')
    assignment = assignments[0]
    match = re.fullmatch(rb'([ \t]*(?:export[ \t]+)?FASTAPI_PORT[ \t]*=[ \t]*)([\'"]?)(5000|5100)\2([ \t]*(?:#[^\r\n]*)?\r?)', assignment.group())
    if not match:
        raise Refused('unexpected_value')
    if match[3] == b'5100':
        return data
    start = assignment.start() + match.start(3)
    return data[:start] + b'5100' + data[start + 4:]


def read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Refused('not_private_regular_file')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise Refused('size_limit')
        return data, info
    finally:
        os.close(fd)


def atomic_write(path, data, mode, uid, gid):
    fd, temporary = tempfile.mkstemp(prefix='.port-alignment-', dir=Path(path).parent)
    try:
        os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def prepare(path):
    original, info = read_regular(path)
    replacement = aligned_bytes(original)
    return original, replacement, info


def apply_locked(path, backup, receipt_path=None):
    """Caller must hold protected deploy lock and production write approval."""
    original, replacement, info = prepare(path)
    if replacement == original:
        return {'status': 'already_aligned'}
    # Create private backup exactly once; never overwrite another operation's backup.
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    receipt = {'status': 'aligned', 'expected_hash': hashlib.sha256(replacement).hexdigest(), 'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
    if receipt_path is not None:
        atomic_write(receipt_path, json.dumps(receipt).encode(), 0o600, 0, 0)
    current, current_info = read_regular(path)
    if current != original or current_info.st_ino != info.st_ino or (current_info.st_mode, current_info.st_uid, current_info.st_gid) != (info.st_mode, info.st_uid, info.st_gid):
        raise Refused('concurrent_config_change')
    atomic_write(path, replacement, stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid)
    verified, after = read_regular(path)
    if verified != replacement or stat.S_IMODE(after.st_mode) != stat.S_IMODE(info.st_mode) or (after.st_uid, after.st_gid) != (info.st_uid, info.st_gid):
        raise Refused('verification_failed')
    # Receipt stays inside protected workflow/host. Never emit file contents or metadata as logs.
    return receipt


def restore_locked(path, backup, receipt):
    current, info = read_regular(path)
    if (stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid) != (receipt['mode'], receipt['uid'], receipt['gid']):
        raise Refused('configuration_metadata_changed')
    if hashlib.sha256(current).hexdigest() != receipt['expected_hash']:
        raise Refused('configuration_changed_since_alignment')
    original, _ = read_regular(backup)
    if aligned_bytes(original) != current:
        raise Refused('backup_mismatch')
    atomic_write(path, original, receipt['mode'], receipt['uid'], receipt['gid'])
    return {'status': 'restored'}

TARGET = Path('/opt/fhd-full/.env')
RECOVERY = Path('/opt/fhd-full-backups/port-alignment-9a7e4cc0')

def artifact_owner(root=Path('/var/www/update/releases/stable/server')):
    data, _ = read_regular(root / 'fhd-manifest.json')
    manifest = json.loads(data)
    artifact = 'fhd-full-1.0.0.7-9a7e4cc0f4fb.tar.gz'
    if manifest.get('git_sha') != '9a7e4cc0f4fbfe07d083d9807eb0f857072e9f4d' or manifest.get('artifact') != artifact or not re.fullmatch(r'[0-9a-f]{64}', str(manifest.get('sha256', ''))):
        return {'verified': False}
    fd = os.open(root / artifact, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            return {'verified': False}
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
        if digest.hexdigest() != manifest['sha256']:
            return {'verified': False}
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode='r|gz') as archive:
            for member in archive:
                if member.name.rstrip('/') in ('XCAGI', './XCAGI'):
                    return {'verified': True, 'directory_member': member.isdir(), 'uid': member.uid, 'gid': member.gid}
    return {'verified': False}

def inspect_state():
    result = {'effective_root': os.geteuid() == 0, 'paths': {}, 'service_restarted': False}
    for path in (Path('/opt'), TARGET.parent, RECOVERY.parent, TARGET, RECOVERY, RECOVERY / '.env.original', RECOVERY / 'receipt.json', Path('/tmp/fhd-auto-update.lock')):
        item = {'exists': os.path.lexists(path)}
        if item['exists']:
            info = path.lstat()
            item.update({'root_owned': info.st_uid == 0, 'group_or_world_writable': bool(info.st_mode & 0o022), 'symlink': stat.S_ISLNK(info.st_mode), 'regular': stat.S_ISREG(info.st_mode), 'directory': stat.S_ISDIR(info.st_mode), 'single_link': info.st_nlink == 1})
        result['paths'][str(path)] = item
    parent_info, target_info = TARGET.parent.lstat(), TARGET.lstat()
    owners = {'parent_matches_file': parent_info.st_uid == target_info.st_uid, 'parent_matches_executor': parent_info.st_uid == os.geteuid(), 'file_matches_executor': target_info.st_uid == os.geteuid()}
    service = subprocess.run(['systemctl', 'show', 'fhd-full.service', '-p', 'User', '--value'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10, check=False)
    if service.returncode == 0:
        user = service.stdout.strip()
        try:
            uid = 0 if not user else int(user) if user.isdigit() else pwd.getpwnam(user).pw_uid
            owners['service_user_resolved'] = True
            owners['parent_matches_service'] = parent_info.st_uid == uid
            owners['file_matches_service'] = target_info.st_uid == uid
        except (KeyError, ValueError):
            owners['service_user_resolved'] = False
    else:
        owners['service_user_resolved'] = False
    result['owner_matches'] = owners
    result['fixed_owner_ids'] = {'parent_uid': parent_info.st_uid, 'parent_gid': parent_info.st_gid, 'target_uid': target_info.st_uid, 'target_gid': target_info.st_gid}
    try:
        pwd.getpwuid(parent_info.st_uid)
        result['parent_owner_account_resolves'] = True
    except KeyError:
        result['parent_owner_account_resolves'] = False
    result['candidate_artifact_owner'] = artifact_owner()
    if any(result['paths'][str(path)].get('symlink', False) for path in (TARGET.parent, RECOVERY.parent, RECOVERY)):
        result['unsafe_parent_symlink'] = True
        return result
    try:
        current, info = read_regular(TARGET)
        replacement = aligned_bytes(current)
        result['port_state'] = '5100' if replacement == current else '5000'
        result['target_parse_ok'] = True
    except (Refused, OSError):
        result['target_parse_ok'] = False
        return result
    backup = RECOVERY / '.env.original'
    receipt_path = RECOVERY / 'receipt.json'
    if os.path.lexists(backup):
        original, _ = read_regular(backup)
        result['current_matches_backup'] = current == original
        result['current_matches_aligned_backup'] = current == aligned_bytes(original)
    if os.path.lexists(receipt_path):
        data, _ = read_regular(receipt_path)
        receipt = json.loads(data)
        result['current_matches_receipt_hash'] = hashlib.sha256(current).hexdigest() == receipt.get('expected_hash')
        result['current_matches_receipt_metadata'] = (stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid) == (receipt.get('mode'), receipt.get('uid'), receipt.get('gid'))
    return result

def main():
    if sys.argv[1:] == ['inspect-port-alignment']:
        print(json.dumps(inspect_state(), sort_keys=True))
        return
    if os.geteuid() != 0 or sys.argv[1:] not in (['align-port-5100'], ['restore-port-5000']):
        raise Refused('fixed_root_action_required')
    for directory in (Path('/opt'), TARGET.parent, RECOVERY.parent):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise Refused('unsafe_parent_directory')
    lock = os.open('/tmp/fhd-auto-update.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
            raise Refused('unsafe_lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not RECOVERY.exists():
            RECOVERY.mkdir(mode=0o700)
        info = RECOVERY.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
            raise Refused('unsafe_recovery_directory')
        backup, receipt_path = RECOVERY / '.env.original', RECOVERY / 'receipt.json'
        if sys.argv[1] == 'align-port-5100':
            result = apply_locked(TARGET, backup, receipt_path)
        else:
            data, _ = read_regular(receipt_path)
            receipt = json.loads(data)
            result = restore_locked(TARGET, backup, receipt)
        print(json.dumps({'status': result['status'], 'action': sys.argv[1], 'service_restarted': False}))
    finally:
        os.close(lock)

if __name__ == '__main__':
    try:
        main()
    except Refused as exc:
        print(json.dumps({'status': 'refused', 'reason': str(exc), 'service_restarted': False}))
        raise SystemExit(1)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired, tarfile.TarError):
        print('{"status":"refused","reason":"os_or_state_error","service_restarted":false}')
        raise SystemExit(1)
