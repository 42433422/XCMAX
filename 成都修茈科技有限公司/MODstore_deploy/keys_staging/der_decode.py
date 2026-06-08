import base64
import pathlib
import subprocess
import sys

def main() -> None:
    p = pathlib.Path("/root/priv.b64").read_text(encoding="utf-8", errors="replace")
    p = p.strip().replace("\r", "").replace("\n", "")
    raw = base64.b64decode(p)
    pathlib.Path("/tmp/pk.der").write_bytes(raw)
    print("der bytes", len(raw), "head", raw[:4].hex())
    outdir = pathlib.Path("/root/test_pem")
    outdir.mkdir(parents=True, exist_ok=True)
    for name, out, args in [
        ("pkcs8", "out8.pem", ["pkcs8", "-in", "/tmp/pk.der", "-inform", "DER", "-nocrypt", "-out", str(outdir / "out8.pem")]),
        ("rsa", "out_rsa.pem", ["rsa", "-in", "/tmp/pk.der", "-inform", "DER", "-out", str(outdir / "out_rsa.pem")]),
    ]:
        r = subprocess.run(["openssl", *args], capture_output=True, text=True)
        if r.returncode == 0:
            print("OK", name, out)
        else:
            print("FAIL", name, r.stderr[:500])


if __name__ == "__main__":
    main()
