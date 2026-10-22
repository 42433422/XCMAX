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
