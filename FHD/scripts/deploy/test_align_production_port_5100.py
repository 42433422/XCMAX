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
if __name__=='__main__':unittest.main()
