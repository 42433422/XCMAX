import re
import base64
import pathlib

t = pathlib.Path("wrap_keys.py").read_text(encoding="utf-8")
s = re.search(r'app_priv = "([^"]+)"', t, re.S).group(1)
d = base64.b64decode(s)
print("b64 len", len(s), "der", len(d), "head", d[:4].hex())
