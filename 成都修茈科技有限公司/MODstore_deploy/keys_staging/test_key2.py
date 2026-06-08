import base64
import re
from pathlib import Path

t = Path("wrap_keys.py").read_text(encoding="utf-8")
s = re.search(r'app_priv = "([^"]+)"', t, re.S).group(1)
s = "".join(s.split())
d = base64.b64decode(s)
enc = base64.b64encode(d).decode("ascii")
print("canonical len", len(enc), "mod4", len(enc) % 4, "end", enc[-2:])
# Try load PKCS8
from cryptography.hazmat.primitives.serialization import load_der_private_key
from cryptography.hazmat.backends import default_backend
k = load_der_private_key(d, password=None, backend=default_backend())
print("load der ok", k.key_size)
