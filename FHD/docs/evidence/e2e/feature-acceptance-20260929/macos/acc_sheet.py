"""为人工目检生成联系表：result.png + 录屏 4 帧（输出到 /tmp，不入仓）。"""
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

FF = "/Users/Shared/XCMAX/FHD/.venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/acc-sheets")


def frames(video: Path, n: int = 4) -> list[Image.Image]:
    with tempfile.TemporaryDirectory() as td:
        probe = subprocess.run([FF, "-i", str(video)], capture_output=True, text=True).stderr
        dur = 10.0
        for line in probe.splitlines():
            if "Duration:" in line:
                h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
                dur = int(h) * 3600 + int(m) * 60 + float(s)
        out = []
        for i in range(n):
            t = dur * (i + 0.5) / n
            p = Path(td) / f"{i}.png"
            subprocess.run([FF, "-v", "quiet", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-y", str(p)])
            if p.is_file():
                out.append(Image.open(p).convert("RGB"))
        return out


def sheet(fid: str) -> Path | None:
    d = ROOT / fid / "macos"
    if not (d / "result.png").is_file():
        return None
    tiles = [Image.open(d / "result.png").convert("RGB")]
    if (d / "operation.webm").is_file():
        tiles += frames(d / "operation.webm")
    w = 900
    big = tiles[0].resize((w, int(tiles[0].height * w / tiles[0].width)))
    small = [t.resize((w // 2, int(t.height * (w // 2) / t.width))) for t in tiles[1:]]
    sh = max((t.height for t in small), default=0)
    rows = (len(small) + 1) // 2
    canvas = Image.new("RGB", (w, big.height + rows * sh + 30), "white")
    ImageDraw.Draw(canvas).text((6, 6), f"{fid}  result.png + operation.webm x{len(small)}", fill="black")
    canvas.paste(big, (0, 30))
    for i, t in enumerate(small):
        canvas.paste(t, ((i % 2) * (w // 2), 30 + big.height + (i // 2) * sh))
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{fid}.jpg"
    canvas.save(p, quality=70)
    return p


if __name__ == "__main__":
    ids = sys.argv[2:] or sorted(p.name for p in ROOT.iterdir() if (p / "draft-run.json").is_file())
    for fid in ids:
        print(fid, sheet(fid))
