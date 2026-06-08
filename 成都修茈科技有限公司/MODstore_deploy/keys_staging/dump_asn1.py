import re
import base64
import subprocess
import tempfile
from pathlib import Path

t = Path("wrap_keys.py").read_text(encoding="utf-8")
s = re.search(r'app_priv = "([^"]+)"', t, re.S).group(1)
s = "".join(s.split())
d = base64.b64decode(s)
Path("der_key.der").write_bytes(d)
print("wrote der", len(d))
r = subprocess.run(
    ["openssl", "asn1parse", "-inform", "DER", "-in", "der_key.der"],
    capture_output=True,
    text=True,
)
print(r.stdout[:800] if r.stdout else r.stderr)
