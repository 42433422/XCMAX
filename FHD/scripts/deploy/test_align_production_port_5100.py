import os
from pathlib import Path
import tempfile
import unittest
from align_production_port_5100 import Refused, aligned_bytes, apply_locked, restore_locked

class Tests(unittest.TestCase):
    def test_single_change_preserves_secret_bytes_permissions_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, backup = Path(tmp)/'.env', Path(tmp)/'backup'
            old=b'SECRET_KEY=do-not-output\r\nFASTAPI_PORT="5000" # keep\r\nOTHER=opaque\r\n'
            path.write_bytes(old);path.chmod(0o640);before=path.stat()
            receipt=apply_locked(path,backup)
            self.assertEqual(path.read_bytes(),old.replace(b'"5000"',b'"5100"'))
            self.assertEqual((path.stat().st_mode,path.stat().st_uid,path.stat().st_gid),(before.st_mode,before.st_uid,before.st_gid))
            self.assertEqual(backup.stat().st_mode & 0o777,0o600)
            self.assertEqual(apply_locked(path,backup),{'status':'already_aligned'})
            self.assertEqual(restore_locked(path,backup,receipt),{'status':'restored'})
            self.assertEqual(path.read_bytes(),old)
    def test_refuses_unknown_duplicate_missing_values(self):
        for data in (b'FASTAPI_PORT=1234\n',b'FASTAPI_PORT=5000\nFASTAPI_PORT=5000\n',b'SECRET=x\n',b'FASTAPI_PORT=${SECRET}\n'):
            with self.assertRaises(Refused):aligned_bytes(data)
    def test_symlink_refused_and_other_change_not_clobbered(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,b=Path(tmp)/'.env',Path(tmp)/'backup';p.write_bytes(b'FASTAPI_PORT=5000\nSECRET=x\n')
            link=Path(tmp)/'link';link.symlink_to(p)
            with self.assertRaises(OSError):apply_locked(link,b)
            receipt=apply_locked(p,b);p.write_bytes(p.read_bytes()+b'OTHER=new\n')
            with self.assertRaises(Refused):restore_locked(p,b,receipt)
            self.assertTrue(p.read_bytes().endswith(b'OTHER=new\n'))
    def test_chmod_only_change_not_clobbered_by_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,b=Path(tmp)/'.env',Path(tmp)/'backup'
            p.write_bytes(b'FASTAPI_PORT=5000\nSECRET=x\n');p.chmod(0o600)
            receipt=apply_locked(p,b);p.chmod(0o640)
            with self.assertRaises(Refused):restore_locked(p,b,receipt)
            self.assertEqual(p.stat().st_mode & 0o777,0o640)
            self.assertIn(b'FASTAPI_PORT=5100',p.read_bytes())
    def test_every_non_config_job_excludes_config_actions(self):
        import yaml
        workflow = Path(__file__).resolve().parents[3] / '.github/workflows/fhd-deploy.yml'
        for name, job in yaml.safe_load(workflow.read_text())['jobs'].items():
            if name != 'fixed-port-configuration':
                self.assertIn("inputs.action != 'align-port-5100'", job['if'], name)
                self.assertIn("inputs.action != 'restore-port-5000'", job['if'], name)
                self.assertIn("inputs.action != 'inspect-port-alignment'", job['if'], name)
        expression = yaml.safe_load(workflow.read_text())['jobs']['report-autonomy-failure']['if']
        expression = expression.removeprefix('${{').removesuffix('}}').strip().replace('&&', ' and ').replace('always()', 'True')
        for old, new in (("inputs.action_id", 'action_id'), ("inputs.environment", 'environment'), ("inputs.action", 'action'), ("needs['cvm-rolling'].result", 'result')):
            expression = expression.replace(old, new)
        for action in ('align-port-5100', 'restore-port-5000', 'inspect-port-alignment', 'apply-latest'):
            for result in ('skipped', 'failure', 'cancelled', 'success'):
                observed = eval(expression, {'__builtins__': {}}, {'action': action, 'result': result, 'environment': 'production', 'action_id': 'fixed'})
                self.assertEqual(observed, action == 'apply-latest' and result != 'success', (action, result))
    def test_config_write_requires_original_exact_sha_security_gate(self):
        import yaml
        workflow = Path(__file__).resolve().parents[3] / '.github/workflows/fhd-deploy.yml'
        job = yaml.safe_load(workflow.read_text())['jobs']['fixed-port-configuration']
        steps = job['steps']
        names = [step.get('name', '') for step in steps]
        gate = names.index('Enforce fresh exact-SHA security clearance')
        write = names.index('Apply only the approved fixed configuration transaction')
        self.assertLess(gate, write)
        self.assertIn('candidate-security-verification/FHD/scripts/security/verify_security_scan_pair.py', steps[gate]['run'])
        self.assertIn('--previous-dir', steps[gate]['run'])
        self.assertIn('--current-dir', steps[gate]['run'])
        self.assertIn('--release-sha', steps[gate]['run'])
        for step in steps[:write+1]:
            self.assertFalse(step.get('continue-on-error', False))
            self.assertNotIn('always()', step.get('if', ''))
        for name in ('Download normalized security evidence', 'Download compatibility security evidence', 'Verify exact candidate checkout'):
            self.assertLess(names.index(name), gate)
        self.assertIn('test "$CURRENT_SCAN" = 41284323055', steps[0]['run'])
        self.assertIn('test "$PREVIOUS_SCAN" = 41284323055', steps[0]['run'])
    def test_inspection_does_not_write_or_disclose_content(self):
        import align_production_port_5100 as module
        from unittest.mock import patch
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / '.env'; recovery = root / 'private'
            target.write_bytes(b'FASTAPI_PORT=5000\nSECRET=NEVER_PRINT_THIS\n')
            before = target.stat()
            with patch.object(module, 'TARGET', target), patch.object(module, 'RECOVERY', recovery), patch.object(module, 'atomic_write', side_effect=AssertionError('write forbidden')), patch.object(module, 'artifact_owner', return_value={'verified': True, 'uid': 1001, 'gid': 1001}), patch.object(module.subprocess, 'run', return_value=type('Result', (), {'returncode': 0, 'stdout': str(os.geteuid())})()):
                result = module.inspect_state()
            self.assertEqual(result['port_state'], '5000')
            self.assertTrue(all(result['owner_matches'].values()))
            self.assertNotIn('NEVER_PRINT_THIS', json.dumps(result))
            self.assertEqual(before.st_mtime_ns, target.stat().st_mtime_ns)
            self.assertFalse(recovery.exists())
    def test_artifact_owner_requires_exact_archive_hash(self):
        import align_production_port_5100 as module
        import tarfile, hashlib, json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); artifact='fhd-full-1.0.0.7-9a7e4cc0f4fb.tar.gz'
            with tarfile.open(root/artifact,'w:gz') as archive:
                member=tarfile.TarInfo('./XCAGI');member.type=tarfile.DIRTYPE;member.uid=1001;member.gid=1001;archive.addfile(member)
            manifest={'git_sha':'9a7e4cc0f4fbfe07d083d9807eb0f857072e9f4d','artifact':artifact,'sha256':hashlib.sha256((root/artifact).read_bytes()).hexdigest()}
            (root/'fhd-manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(module.artifact_owner(root),{'verified':True,'directory_member':True,'uid':1001,'gid':1001})
            manifest['sha256']='0'*64;(root/'fhd-manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(module.artifact_owner(root),{'verified':False})
if __name__=='__main__':unittest.main()
