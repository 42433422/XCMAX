import base64
import re
from pathlib import Path

t = Path("wrap_keys.py").read_text(encoding="utf-8")
s = re.search(r'app_priv = "([^"]+)"', t, re.S).group(1)
s = "".join(s.split())
for name, x in [("orig", s), ("strip1", s.rstrip("=")), ("first1624", s[:1624])]:
    try:
        d = base64.b64decode(x)
        print(name, "len b64", len(x), "der", len(d), "head", d[:6].hex())
    except Exception as e:
        print(name, e)
