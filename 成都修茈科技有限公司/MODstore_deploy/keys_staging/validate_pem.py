import pathlib
import re
import base64

t = pathlib.Path("wrap_keys.py").read_text(encoding="utf-8")
s = re.search(r'app_priv = "([^"]+)"', t, re.S).group(1)
p = pathlib.Path("app_private_key.pem").read_text(encoding="utf-8")
body = "".join(
    line.strip() for line in p.splitlines() if line.strip() and "BEGIN" not in line and "END" not in line
)
print("source==pem_body", s == body, len(s), len(body))
if s != body:
    for i, (a, b) in enumerate(zip(s, body)):
        if a != b:
            print("first diff", i, repr(a), repr(b))
            break
d1, d2 = base64.b64decode(s), base64.b64decode(body)
print("der len", len(d1), len(d2), d1 == d2)
