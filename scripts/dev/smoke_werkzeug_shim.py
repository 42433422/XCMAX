# -*- coding: utf-8 -*-
"""一次性冒烟：password_hash 与 secure_filename 相对 werkzeug 的等价性。"""

from __future__ import annotations

import hashlib

from app.utils.password_hash import check_password_hash, generate_password_hash
from app.utils.secure_filename import secure_filename


def check_roundtrip() -> None:
    h = generate_password_hash("s3cret")
    assert h.startswith("pbkdf2:sha256:"), h
    assert check_password_hash(h, "s3cret") is True
    assert check_password_hash(h, "wrong") is False
    print("stdlib round-trip OK:", h[:40], "...")


def check_cross_compat() -> None:
    try:
        from werkzeug.security import (
            check_password_hash as wz_chk,
            generate_password_hash as wz_gen,
        )
    except ImportError:
        print("werkzeug not installed; skipping cross-compat")
        return

    wz_hash = wz_gen("hello")
    method = wz_hash.split("$", 1)[0]
    print("werkzeug produced:", wz_hash[:60], "... method=" + method)

    if method.startswith("pbkdf2:") or method.startswith("scrypt:"):
        ok = check_password_hash(wz_hash, "hello")
        print("shim verifies werkzeug hash:", ok)
        assert ok, "BACKWARD COMPAT BROKEN"
    else:
        print("unexpected method from werkzeug:", method)

    shim_hash = generate_password_hash("topsecret")
    ok2 = wz_chk(shim_hash, "topsecret")
    print("werkzeug verifies shim hash:", ok2)
    assert ok2, "FORWARD COMPAT BROKEN"


def check_scrypt_verify() -> None:
    salt = "abc123"
    n, r, p = 32768, 8, 1
    hexed = hashlib.scrypt(
        b"swordfish",
        salt=salt.encode(),
        n=n,
        r=r,
        p=p,
        maxmem=132 * 1024 * 1024,
        dklen=64,
    ).hex()
    scrypt_hash = f"scrypt:{n}:{r}:{p}${salt}${hexed}"
    assert check_password_hash(scrypt_hash, "swordfish") is True
    assert check_password_hash(scrypt_hash, "wrong") is False
    print("scrypt verify path OK")


def check_secure_filename() -> None:
    assert secure_filename("My cool movie.mov") == "My_cool_movie.mov"
    assert secure_filename("../../../etc/passwd") == "etc_passwd"
    assert secure_filename("i contain cool \xfcml\xe4uts.txt") == "i_contain_cool_umlauts.txt"
    assert secure_filename("  ..hidden..  ") == "hidden"
    assert secure_filename("Normal_file-v1.txt") == "Normal_file-v1.txt"
    print("secure_filename OK")

    # 对照 werkzeug 原版（若可用）
    try:
        from werkzeug.utils import secure_filename as wz_sf
    except ImportError:
        print("werkzeug.utils not installed; skipping secure_filename parity")
        return
    samples = [
        "My cool movie.mov",
        "../../../etc/passwd",
        "i contain cool \xfcml\xe4uts.txt",
        "  ..hidden..  ",
        "CON.txt",
        "\u4e2d\u6587\u6587\u4ef6.txt",
        "foo/bar/baz.ext",
        "\\windows\\path.txt",
    ]
    diffs: list[tuple[str, str, str]] = []
    for s in samples:
        a, b = secure_filename(s), wz_sf(s)
        if a != b:
            diffs.append((s, a, b))
    if diffs:
        print("secure_filename parity DIFF:")
        for s, a, b in diffs:
            print(f"  input={s!r}  shim={a!r}  werkzeug={b!r}")
        raise AssertionError("secure_filename diverges from werkzeug")
    print("secure_filename parity with werkzeug: OK")


if __name__ == "__main__":
    check_roundtrip()
    check_cross_compat()
    check_scrypt_verify()
    check_secure_filename()
    print("\nALL WERKZEUG SHIM SMOKE CHECKS PASSED")
