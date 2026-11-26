"""Compare decoded screenshot pixels. Candidate images never replace the baseline."""
import argparse
import hashlib
import json
import struct
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

# Exact planned captures for the current specs; count drift must fail until reviewed.
EXPECTED = {"desktop": 16, "market": 19, "flutter": 40}
NEW_CASES = {
    "market": {
        f"autonomy-{state}-{width}.png"
        for state in ("collapsed", "open", "preview")
        for width in (375, 1440)
    }
}


def pixel_hash(image):
    return hashlib.sha256(struct.pack(">II", *image.size) + image.tobytes()).hexdigest()


def read_image(path):
    with Image.open(path) as image:
        return image.convert("RGBA")


def compare(root, surface, base_sha, candidate_sha, manifest):
    base = {p.name: p for p in (root / "baseline").glob("*.png")}
    candidate = {p.name: p for p in (root / "candidate").glob("*.png")}
    approvals = manifest["surfaces"].get(surface, {}) if manifest["base_sha"] == base_sha else {}
    if not isinstance(approvals, dict):
        raise ValueError("surface approvals must be an object")
    report = {"surface": surface, "base_sha": base_sha, "candidate_sha": candidate_sha,
              "expected_case_count": EXPECTED.get(surface, 1),
              "baseline_case_count": len(base), "candidate_case_count": len(candidate),
              "cases": [], "unused_approvals": []}
    ok = len(candidate) == EXPECTED.get(surface, 1)
    used = set()
    diff_dir = root / "diff"
    diff_dir.mkdir(parents=True, exist_ok=True)
    for name in sorted(base.keys() | candidate.keys()):
        row = {"name": name}
        report["cases"].append(row)
        if name not in candidate:
            row["status"] = "missing_candidate"
            ok = False
            continue
        b = read_image(candidate[name])
        if name not in base:
            pair = {"baseline": None, "candidate": pixel_hash(b)}
            row.update(pair, candidate_size=b.size)
            if name in NEW_CASES.get(surface, ()) and approvals.get(name) == pair:
                row["status"] = "explicitly_approved_new_case"
                used.add(name)
            else:
                row["status"] = "missing_baseline"
                ok = False
            continue
        a = read_image(base[name])
        pair = {"baseline": pixel_hash(a), "candidate": pixel_hash(b)}
        row.update(pair)
        row["baseline_size"], row["candidate_size"] = a.size, b.size
        if a.size != b.size:
            row["status"] = "dimension_mismatch"
            ok = False
            continue
        if pair["baseline"] == pair["candidate"]:
            row["status"] = "unchanged"
            continue
        channels = ImageChops.difference(a, b).split()
        mask = channels[0]
        for channel in channels[1:]:
            mask = ImageChops.lighter(mask, channel)
        mask = mask.point(lambda value: 255 if value else 0)
        row["changed_pixels"] = mask.histogram()[255]
        overlay = b.convert("RGB")
        overlay.paste((255, 0, 255), mask=mask)
        overlay.save(diff_dir / name)
        if approvals.get(name) == pair:
            row["status"] = "explicitly_approved"
            used.add(name)
        else:
            row["status"] = "unapproved_visual_change"
            ok = False
    report["unused_approvals"] = sorted(set(approvals) - used)
    ok = ok and not report["unused_approvals"]
    report["pass"] = ok
    (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    return ok, report


def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for folder in ["baseline", "candidate"]:
            (root / folder).mkdir()
        a = Image.new("RGBA", (16, 16), "white")
        a.save(root / "baseline" / "probe.png")
        a.save(root / "candidate" / "probe.png")
        empty = {"base_sha": None, "surfaces": {}}
        assert compare(root, "probe", "base", "head", empty)[0]
        b = a.copy()
        b.putpixel((1, 1), (0, 0, 0, 255))
        b.save(root / "candidate" / "probe.png")
        ok, report = compare(root, "probe", "base", "head", empty)
        assert not ok and report["cases"][0]["changed_pixels"] == 1
        assert (root / "diff" / "probe.png").is_file()
        approval = {"base_sha": "base", "surfaces": {"probe": {"probe.png": {
            "baseline": pixel_hash(a), "candidate": pixel_hash(b)}}}}
        assert compare(root, "probe", "base", "head", approval)[0]
        assert not compare(root, "probe", "different-base", "head", approval)[0]
        b.putpixel((2, 2), (0, 0, 0, 255))
        b.save(root / "candidate" / "probe.png")
        assert not compare(root, "probe", "base", "head", approval)[0]
        (root / "candidate" / "probe.png").unlink()
        assert not compare(root, "probe", "base", "head", empty)[0]
        (root / "baseline" / "probe.png").unlink()
        assert not compare(root, "probe", "base", "head", empty)[0]
        existing_count = EXPECTED["market"] - len(NEW_CASES["market"])
        ordinary_cases = {f"unchanged-{i}.png" for i in range(existing_count)}
        for name in ordinary_cases | NEW_CASES["market"]:
            a.save(root / "candidate" / name)
        for name in ordinary_cases:
            a.save(root / "baseline" / name)
        approved_new = {name: {"baseline": None, "candidate": pixel_hash(a)} for name in NEW_CASES["market"]}
        approval = {"base_sha": "base", "surfaces": {"market": approved_new}}
        assert not compare(root, "market", "base", "head", empty)[0]
        assert compare(root, "market", "base", "head", approval)[0]
        assert not compare(root, "market", "different-base", "head", approval)[0]
        name = min(NEW_CASES["market"])
        b.save(root / "candidate" / name)
        assert not compare(root, "market", "base", "head", approval)[0]
        (root / "candidate" / name).unlink()
        assert not compare(root, "market", "base", "head", approval)[0]
        a.save(root / "candidate" / name)
        unexpected = min(ordinary_cases)
        (root / "baseline" / unexpected).unlink()
        approved_new[unexpected] = {"baseline": None, "candidate": pixel_hash(a)}
        assert not compare(root, "market", "base", "head", approval)[0]
    print("visual comparator positive/negative controls PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--surface", choices=list(EXPECTED))
    parser.add_argument("--base-sha")
    parser.add_argument("--candidate-sha")
    parser.add_argument("--approvals", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if not all((args.root, args.surface, args.base_sha, args.candidate_sha, args.approvals)):
            parser.error("comparison requires root, surface, both source SHAs and approvals")
        manifest = json.loads(args.approvals.read_text(encoding="utf-8"))
        ok, report = compare(args.root, args.surface, args.base_sha, args.candidate_sha, manifest)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if ok else 1)
