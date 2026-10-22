# shellcheck shell=bash
# Preserve the exact failed-apply workspace before cleanup when rollback is incomplete.

fhd_preserve_recovery_material() {
  local source="${1:?source workspace is required}"
  local backup="${2:?backup directory is required}"
  local label="${3:?recovery label is required}"
  local destination="$backup/recovery-$label"
  local marker="$backup/.recovery-required"

  [[ -d "$source" && ! -L "$source" ]] || {
    echo "[deploy] ERROR: recovery source is missing or unsafe: $source" >&2
    return 1
  }
  mkdir -m 700 -- "$destination" || {
    echo "[deploy] ERROR: cannot create protected recovery directory: $destination" >&2
    return 1
  }
  (umask 077; printf '%s\n' "$destination" >> "$marker") || {
    echo "[deploy] ERROR: cannot protect recovery backup from pruning: $backup" >&2
    return 1
  }
  chmod 600 "$marker" || {
    echo "[deploy] ERROR: cannot secure recovery marker: $marker" >&2
    return 1
  }
  if ! cp -a -- "$source/." "$destination/"; then
    echo "[deploy] ERROR: recovery copy failed; original material retained at $source" >&2
    return 1
  fi
  if ! python3 - "$source" "$destination" <<'PY'
import hashlib
import json
import os
import stat
import sys

def tree_digest(root):
    rows = []
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        names = sorted(dirs + files)
        dirs[:] = sorted(name for name in dirs if not os.path.islink(os.path.join(current, name)))
        for name in names:
            path = os.path.join(current, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            info = os.lstat(path)
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                row = (rel, "link", mode, os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                row = (rel, "dir", mode, "")
            elif stat.S_ISREG(info.st_mode):
                digest = hashlib.sha256()
                with open(path, "rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                row = (rel, "file", mode, digest.hexdigest())
            else:
                raise SystemExit("unsupported recovery entry: " + rel)
            rows.append(row)
    payload = json.dumps(sorted(rows), separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()

if tree_digest(sys.argv[1]) != tree_digest(sys.argv[2]):
    raise SystemExit("recovery copy does not match its source")
PY
  then
    echo "[deploy] ERROR: recovery copy verification failed; original material retained at $source" >&2
    return 1
  fi
  echo "[deploy] Recovery material preserved and verified at $destination" >&2
}


# Commit the rollback archive and identity stamps as one recoverable transaction.
# A pending marker closes the apply path if interrupted between atomic renames.
fhd_commit_release_identity() {
  local archive="${1:?release archive is required}"
  local deploy_root="${2:?deploy root is required}"
  local backup="${3:?backup directory is required}"
  local archive_sha="${4:?archive SHA256 is required}"
  local git_sha="${5:?Git SHA is required}"
  local admin_sha="${6:?admin console SHA256 is required}"
  python3 - "$archive" "$deploy_root" "$backup" "$archive_sha" "$git_sha" "$admin_sha" <<'PY'
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile

archive, root, backup = map(Path, sys.argv[1:4])
expected_sha, git_sha, admin_sha = sys.argv[4:]
stamps = {
    ".deploy-sha256": (expected_sha + "\n").encode(),
    ".deploy-git-sha": (git_sha + "\n").encode(),
    ".deploy-admin-console-sha256": (admin_sha + "\n").encode(),
}
if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or not re.fullmatch(r"[0-9a-f]{40}", git_sha) or not re.fullmatch(r"[0-9a-f]{64}", admin_sha):
    raise SystemExit("invalid release identity")
if not root.is_dir() or root.is_symlink() or not backup.is_dir() or backup.is_symlink():
    raise SystemExit("deploy root or recovery backup is unsafe")

def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try: os.fsync(fd)
    finally: os.close(fd)

def stage(name, payload):
    fd, temp = tempfile.mkstemp(prefix=f".{name}.stage-", dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        return Path(temp)
    except BaseException:
        try: os.unlink(temp)
        except FileNotFoundError: pass
        raise

temps = []
try:
    digest = hashlib.sha256()
    archive_fd, archive_tmp = tempfile.mkstemp(prefix=".deploy-last.tar.gz.stage-", dir=root)
    temps.append(Path(archive_tmp))
    with os.fdopen(archive_fd, "wb") as output, archive.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            output.write(block)
            digest.update(block)
        output.flush()
        os.fsync(output.fileno())
    if digest.hexdigest() != expected_sha:
        raise SystemExit("staged rollback archive digest mismatch")
    os.chmod(archive_tmp, 0o600)
    for name, payload in stamps.items():
        temps.append(stage(name, payload))
    backup_hold = backup / ".deploy-identity-pending"
    if backup_hold.exists() or backup_hold.is_symlink():
        raise SystemExit("recovery backup already has a pending identity transaction")
    hold_fd = os.open(backup_hold, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(hold_fd, "w", encoding="utf-8") as hold:
        hold.write(str(root / ".deploy-identity-pending") + "\n")
        hold.flush()
        os.fsync(hold.fileno())
    fsync_dir(backup)
    pending_tmp = stage(".deploy-identity-pending", (str(backup) + "\n").encode())
    temps.append(pending_tmp)
    pending = root / ".deploy-identity-pending"
    if pending.exists() or pending.is_symlink():
        raise SystemExit("a previous deployment identity transaction needs recovery: " + str(pending))
    os.replace(pending_tmp, pending)
    fsync_dir(root)
    os.replace(archive_tmp, root / ".deploy-last.tar.gz")
    for name in stamps:
        staged = next(path for path in temps if path.name.startswith(f".{name}.stage-"))
        os.replace(staged, root / name)
    fsync_dir(root)
    if hashlib.sha256((root / ".deploy-last.tar.gz").read_bytes()).hexdigest() != expected_sha:
        raise SystemExit("committed rollback archive digest mismatch")
except BaseException:
    for temp in temps:
        try: temp.unlink()
        except FileNotFoundError: pass
    raise
PY
}

fhd_complete_release_identity() {
  local deploy_root="${1:?deploy root is required}"
  local backup="${2:?backup directory is required}"
  local archive_sha="${3:?archive SHA256 is required}"
  local git_sha="${4:?Git SHA is required}"
  local admin_sha="${5:?admin console SHA256 is required}"
  python3 - "$deploy_root" "$backup" "$archive_sha" "$git_sha" "$admin_sha" <<'PY'
import hashlib
import os
from pathlib import Path
import sys
root, backup = map(Path, sys.argv[1:3])
expected_sha, git_sha, admin_sha = sys.argv[3:]
expected = {".deploy-sha256": expected_sha, ".deploy-git-sha": git_sha,
            ".deploy-admin-console-sha256": admin_sha}
pending = root / ".deploy-identity-pending"
if pending.is_symlink() or not pending.is_file():
    raise SystemExit("release identity transaction marker is missing")
if pending.read_text(encoding="utf-8").strip() != str(backup):
    raise SystemExit("release identity transaction belongs to another backup")
archive = root / ".deploy-last.tar.gz"
if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected_sha:
    raise SystemExit("committed rollback archive does not match release identity")
for name, value in expected.items():
    if (root / name).read_text(encoding="ascii").strip() != value:
        raise SystemExit("committed identity stamp mismatch: " + name)
(root / ".deploy-identity-pending").unlink()
fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try: os.fsync(fd)
finally: os.close(fd)
hold = backup / ".deploy-identity-pending"
try: hold.unlink()
except FileNotFoundError: pass
else:
    fd = os.open(backup, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try: os.fsync(fd)
    finally: os.close(fd)
PY
}

# Restore the old identity anchor after an interrupted/failed commit.  The
# pending markers remain unless every saved file has been restored and checked.
fhd_restore_release_identity() {
  local deploy_root="${1:?deploy root is required}"
  local backup="${2:?backup directory is required}"
  python3 - "$deploy_root" "$backup" <<'PY'
import os
from pathlib import Path
import shutil
import sys
import tempfile
root, backup = map(Path, sys.argv[1:3])
pending = root / ".deploy-identity-pending"
if not pending.exists() and not pending.is_symlink():
    raise SystemExit(0)
if pending.is_symlink() or not pending.is_file() or backup.is_symlink() or not backup.is_dir():
    raise SystemExit("pending release identity recovery path is unsafe")
if pending.read_text(encoding="utf-8").strip() != str(backup):
    raise SystemExit("release identity transaction belongs to another backup")
names = [".deploy-last.tar.gz", ".deploy-sha256", ".deploy-git-sha", ".deploy-admin-console-sha256"]
def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try: os.fsync(fd)
    finally: os.close(fd)
for name in names:
    source, target = backup / name, root / name
    if source.exists():
        if source.is_symlink() or not source.is_file():
            raise SystemExit("unsafe saved identity file: " + str(source))
        fd, temp = tempfile.mkstemp(prefix=f".{name}.restore-", dir=root)
        try:
            with os.fdopen(fd, "wb") as output, source.open("rb") as inp:
                shutil.copyfileobj(inp, output)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, target)
        finally:
            try: os.unlink(temp)
            except FileNotFoundError: pass
    else:
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise SystemExit("unsafe current identity path: " + str(target))
        try: target.unlink()
        except FileNotFoundError: pass
fsync_dir(root)
for name in names:
    source, target = backup / name, root / name
    if source.exists() != target.exists() or (source.exists() and source.read_bytes() != target.read_bytes()):
        raise SystemExit("restored release identity did not verify: " + name)
pending.unlink()
fsync_dir(root)
hold = backup / ".deploy-identity-pending"
try: hold.unlink()
except FileNotFoundError: pass
else: fsync_dir(backup)
PY
}
