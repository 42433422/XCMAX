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
        expression = yaml.safe_load(workflow.read_text())['jobs']['report-autonomy-failure']['if']
        expression = expression.removeprefix('${{').removesuffix('}}').strip().replace('&&', ' and ').replace('always()', 'True')
        for old, new in (("inputs.action_id", 'action_id'), ("inputs.environment", 'environment'), ("inputs.action", 'action'), ("needs['cvm-rolling'].result", 'result')):
            expression = expression.replace(old, new)
        for action in ('align-port-5100', 'restore-port-5000', 'apply-latest'):
            for result in ('skipped', 'failure', 'cancelled', 'success'):
                observed = eval(expression, {'__builtins__': {}}, {'action': action, 'result': result, 'environment': 'production', 'action_id': 'fixed'})
                self.assertEqual(observed, action == 'apply-latest' and result != 'success', (action, result))
if __name__=='__main__':unittest.main()
