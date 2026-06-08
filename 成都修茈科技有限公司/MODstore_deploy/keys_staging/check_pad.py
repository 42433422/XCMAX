import re
import base64

t = open("wrap_keys.py", encoding="utf-8").read()
s = re.search(r'app_priv = "([^"]+)"', t, re.S).group(1)
print("len", len(s), "ends", s[-3:], "mod4", len(s) % 4)
d1 = base64.b64decode(s, validate=True)
d2 = base64.b64decode(s.rstrip("="))
print("decode validate", len(d1), "rstrip", len(d2), d1 == d2)
try:
    base64.b64decode(s + "=", validate=True)  # noqa: wrong
except Exception as e:
    print("err", e)

s1624 = s.rstrip("=")  # 1624 chars if we remove one =
print("after rstrip =", len(s1624), len(s1624) % 4, len(base64.b64decode(s1624)))
