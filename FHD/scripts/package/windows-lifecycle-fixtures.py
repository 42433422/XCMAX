"""Synthetic, isolated owned-state fixtures; never creates rollback state."""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(action, root, evidence):
    root, evidence = Path(root), Path(evidence)
    if action in ('main-seed', 'main-verify', 'backup-verify'):
        database = root if action == 'backup-verify' else root / 'data' / 'xcagi.db'
        assert database.is_file(), 'Existing isolated application database required'
        with sqlite3.connect(f'file:{database.as_posix()}?mode={"rw" if action == "main-seed" else "ro"}', uri=True) as db:
            if action == 'main-seed':
                db.execute('CREATE TABLE lifecycle_acceptance_records (id INTEGER PRIMARY KEY, value TEXT)')
                db.execute("INSERT INTO lifecycle_acceptance_records VALUES (1, 'synthetic-lifecycle-record')")
            assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
            assert db.execute('SELECT * FROM lifecycle_acceptance_records').fetchall() == [(1, 'synthetic-lifecycle-record')]
        print(json.dumps({'action': action, 'provenance': 'synthetic isolated fixture; not customer or UI business data', 'rows': 1}))
        return
    if action in ('app-seed', 'app-verify'):

        manifest = evidence / 'original-app-files.json'
        if action == 'app-seed':
            manifest.write_text(json.dumps({str(p.relative_to(root)): digest(p) for p in root.rglob('*') if p.is_file()}), encoding='utf-8')
        expected = json.loads(manifest.read_text(encoding='utf-8'))
        assert expected and all(digest(root / name) == value for name, value in expected.items())
        assert set(expected) == {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
        print(json.dumps({'action': action, 'files': len(expected)}))
        return
    manifest = evidence / 'owned-fixtures.json'
    if action == 'seed':
        assert not manifest.exists(), 'Fixture manifest already exists'
        base = root / 'mods' / 'lifecycle-acceptance'
        long_dir = base / ('a' * 60) / ('b' * 60)
        # Exactly 261 characters in the ordinary absolute Windows path, not a \\?\ prefix.
        name_size = 261 - len(str(long_dir)) - 1 - len('.bin')
        assert 1 <= name_size <= 250, (str(long_dir), name_size)
        files = [base / 'config.json', base / 'attachments' / 'sample.txt', long_dir / ('c' * name_size + '.bin'), root / 'data' / 'mod_dbs' / 'lifecycle-acceptance' / 'private.db']
        for file in files:
            file.parent.mkdir(parents=True, exist_ok=True)
            assert not file.exists(), 'Refusing to overwrite existing user data'
            if file.suffix == '.db':
                with sqlite3.connect(file) as db:
                    db.execute('CREATE TABLE acceptance_records (id INTEGER PRIMARY KEY, value TEXT)')
                    db.execute("INSERT INTO acceptance_records VALUES (1, 'synthetic-private-record')")
            else:
                file.write_text('{"fixture":"synthetic-lifecycle","value":42}\n', encoding='utf-8')
        manifest.write_text(json.dumps([{'path': str(p.relative_to(root)), 'sha256': digest(p), 'bytes': p.stat().st_size, 'absolute_length': len(str(p))} for p in files]), encoding='utf-8')
    entries = json.loads(manifest.read_text(encoding='utf-8'))
    if action == 'dirty':
        for entry in entries:
            file = root / entry['path']
            if file.suffix == '.db':
                with sqlite3.connect(file) as db:
                    db.execute("UPDATE acceptance_records SET value='controlled-failure'")
            else:
                file.write_text('controlled-failure\n', encoding='utf-8')
        # Touch a dedicated table only, after the app's own database backup exists.
        with sqlite3.connect(root / 'data' / 'xcagi.db') as db:
            db.execute('CREATE TABLE lifecycle_failure_probe (value TEXT)')
            db.execute("INSERT INTO lifecycle_failure_probe VALUES ('controlled-failure')")
    if action == 'verify':
        for entry in entries:
            file = root / entry['path']
            assert digest(file) == entry['sha256'], f'Owned-state mismatch: {entry["path"]}'
            if file.suffix == '.db':
                with sqlite3.connect(f'file:{file.as_posix()}?mode=ro', uri=True) as db:
                    assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
                    assert db.execute('SELECT * FROM acceptance_records').fetchall() == [(1, 'synthetic-private-record')]
        assert any(e['absolute_length'] == 261 for e in entries)
    print(json.dumps({'action': action, 'files': len(entries), 'longest_path': max(e['absolute_length'] for e in entries)}))


if __name__ == '__main__':
    run(*sys.argv[1:])
