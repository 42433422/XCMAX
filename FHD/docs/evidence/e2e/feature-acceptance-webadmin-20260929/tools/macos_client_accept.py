#!/usr/bin/env python3
"""macOS 桌面客户端（已安装 XCAGI.app）真机验收执行器。

真实性边界（不得放宽）：
  * 被测对象是**已安装到 /Applications 的真实客户端**：本轮真实启动它（隔离端口与隔离 userData，
    不影响其它正在运行的实例），用 CDP 连接它的真实渲染进程做断言与截图。
  * 交付物身份（DMG / 应用包 / 代码签名 / 公证 / Gatekeeper）全部在本轮**现场重算**，
    不复用历史验收证据。
  * 录像由本轮真实渲染帧（CDP Page.startScreencast）编码而成，帧来自被测客户端自身画面。
  * 只按产品既有行为判定；产品确实不具备的行为如实记为观察项，不写进预期。
  * 凭据不落盘。media[] 一律先写 pending_review，人工复核后才允许改。

用法：
  python3.11 macos_client_accept.py --spec specs/<feature>.py
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

# 本机系统代理会把 127.0.0.1 也送进代理，导致 CDP/健康检查 502 假阴性；
# 这里显式声明本地直连白名单，Playwright 与本进程的 HTTP 客户端都会遵守。
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,::1")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost,::1")

import argparse

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parents[5]
APP_BUNDLE = Path("/Applications/XCAGI.app")
APP_EXEC = APP_BUNDLE / "Contents/MacOS/XCAGI"
BUILD_INFO = APP_BUNDLE / "Contents/Resources/build-info.json"
DMG = Path("/Users/Shared/XCAGI-FULLCLOSED-20260928/artifact/XCAGI-Enterprise-1.0.0.5-mac-arm64.dmg")
BACKEND_PORT = int(os.environ.get("XCAGI_MAC_ACCEPT_PORT", "17650"))
CDP_PORT = int(os.environ.get("XCAGI_MAC_ACCEPT_CDP", "9224"))
USER_DATA = Path(os.environ.get("XCAGI_MAC_ACCEPT_USERDATA", "/Users/Shared/xcmax-vc-macclient"))
FFMPEG = "/Users/a4243342/Library/Caches/ms-playwright/ffmpeg-1011/ffmpeg-mac"

LOG_LINES: list[str] = []


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    LOG_LINES.append(line)
    print(line, flush=True)


def sha256_file(p: Path) -> str | None:
    h = hashlib.sha256()
    if not p.is_file():
        return None
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_cmd(args: list[str], timeout: int = 120) -> dict:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {"argv": " ".join(args), "exit_code": p.returncode,
                "stdout": (p.stdout or "").strip()[-500:], "stderr": (p.stderr or "").strip()[-500:]}
    except subprocess.SubprocessError as exc:
        return {"argv": " ".join(args), "exit_code": -1, "stdout": "", "stderr": str(exc)}


def no_proxy_json(url: str, timeout: int = 8):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc)}


def wait_until(fn, timeout: float, label: str):
    started = time.time()
    while time.time() - started < timeout:
        try:
            if fn():
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    log(f"wait: TIMEOUT {label}")
    return False


def load_spec(path: Path):
    spec = importlib.util.spec_from_file_location("accept_spec", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def encode_video(frames_dir: Path, out_file: Path) -> Path | None:
    frames = sorted(frames_dir.glob("f-*.jpg"))
    if not frames:
        return None
    # Playwright 自带的精简 ffmpeg 只有 image2pipe 解复用器 + mjpeg 解码器 + libvpx 编码器，
    # 且不支持 pipe: 协议（只认 file:），因此用 /dev/stdin 按 MJPEG 流顺序喂真实渲染帧编码成 webm。
    argv = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe", "-c:v", "mjpeg",
            "-framerate", "5", "-i", "/dev/stdin", "-vf", "format=yuv420p", "-c:v", "libvpx", "-b:v", "1200k",
            str(out_file)]
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE)
        for f in frames:
            proc.stdin.write(f.read_bytes())
        proc.stdin.flush()
        proc.stdin.close()
        err = proc.stderr.read()
        proc.wait(timeout=300)
        code = proc.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"video encode failed: {exc}")
        return None
    if code != 0 or not out_file.is_file() or out_file.stat().st_size == 0:
        log(f"video encode failed: exit={code} err={(err or b'').decode('utf-8', 'replace')[:220]}")
        return None
    return out_file


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    spec_path = Path(args.spec).resolve()
    mod = load_spec(spec_path)
    feature = mod.FEATURE
    platform = getattr(mod, "PLATFORM", "macos")
    out = Path(args.out).resolve() if args.out else spec_path.parent.parent / "runs" / feature
    shot_dir, video_dir, log_dir, frames_dir = out / "shot", out / "video", out / "log", out / "frames"
    for d in (shot_dir, video_dir, log_dir, frames_dir):
        d.mkdir(parents=True, exist_ok=True)
    for stale in list(shot_dir.glob("*.png")) + list(video_dir.glob("*")) + list(frames_dir.glob("*")):
        stale.unlink()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log(f"feature={feature} platform={platform} out={out}")

    if not APP_EXEC.is_file():
        log(f"FATAL: 未找到已安装客户端 {APP_EXEC}")
        return 2
    build = json.loads(BUILD_INFO.read_text(encoding="utf-8"))
    app_sha, app_version = str(build.get("gitSha") or ""), str(build.get("version") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", app_sha):
        log(f"FATAL: 已安装客户端 build-info 无有效 gitSha ({app_sha!r})")
        return 2
    log(f"installed app: version={app_version} gitSha={app_sha}")

    USER_DATA.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "XCAGI_DESKTOP_PORT": str(BACKEND_PORT),
        "XCAGI_DESKTOP_USER_DATA_DIR": str(USER_DATA),
        "XCAGI_DESKTOP_MODE": "1",
    })
    log(f"launching isolated instance: port={BACKEND_PORT} userdata={USER_DATA} cdp={CDP_PORT}")
    proc = subprocess.Popen(
        [str(APP_EXEC), f"--remote-debugging-port={CDP_PORT}", "--remote-allow-origins=*"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(APP_BUNDLE / "Contents/MacOS"),
    )
    backend_base = f"http://127.0.0.1:{BACKEND_PORT}"
    ok_cdp = wait_until(lambda: no_proxy_json(f"http://127.0.0.1:{CDP_PORT}/json/version").get("Browser"), 90, "cdp")
    ok_be = wait_until(lambda: no_proxy_json(backend_base + "/api/health").get("status"), 120, "backend health")
    log(f"launch: cdp={ok_cdp} backend={ok_be} pid={proc.pid}")

    cases: list[dict] = []
    media: list[dict] = []
    observations = [f"本轮真实启动已安装客户端（隔离端口 {BACKEND_PORT}、隔离 userData），CDP {CDP_PORT}。"]
    observations.extend(getattr(mod, "EXTRA_OBSERVATIONS", []) or [])

    from playwright.sync_api import sync_playwright

    api_health = no_proxy_json(backend_base + "/api/health")
    env_ctx = {"base": backend_base, "shot": shot_dir, "log": log,
               "launch": {"cdp": ok_cdp, "backend": ok_be, "pid": proc.pid}, "app": dict(build)}
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}", timeout=60000)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.wait_for_timeout(3000)
            cdp = ctx.new_cdp_session(page)
            frames = {"n": 0}

            def on_frame(params):
                frames["n"] += 1
                f = frames_dir / f"f-{frames['n']:05d}.jpg"
                f.write_bytes(base64.b64decode(params["data"]))
                try:
                    cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
                except Exception:  # noqa: BLE001
                    pass

            cdp.on("Page.screencastFrame", on_frame)
            try:
                cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 85, "everyNthFrame": 1})
            except Exception as exc:  # noqa: BLE001
                log(f"screencast start failed: {exc}")

            for cs in mod.CASES:
                cid, title = cs["id"], cs["title"]
                try:
                    observed, passed = cs["run"](page, env_ctx)
                except Exception as exc:  # noqa: BLE001
                    observed, passed = {"exception": f"{type(exc).__name__}: {exc}"}, False
                cases.append({"id": cid, "title": title, "input": cs["input"], "actions": cs["actions"],
                              "expected": cs["expected"],
                              "observed": json.dumps(observed, ensure_ascii=False, default=str),
                              "result": "passed" if passed else "failed"})
                log(f"case {cid}: {'passed' if passed else 'failed'} - {title}")

            try:
                cdp.send("Page.stopScreencast")
            except Exception:  # noqa: BLE001
                pass
            page.screenshot(path=str(shot_dir / "99-final-state.png"))
            log(f"screencast frames: {frames['n']}")
    finally:
        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=25)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        log("client terminated")

    video_path = encode_video(frames_dir, video_dir / f"{feature}-{platform}-{stamp}.webm")
    log(f"video: {video_path.name if video_path else 'NOT produced'} "
        f"({video_path.stat().st_size if video_path else 0} bytes)")

    def rel(p: Path) -> str:
        return str(p.resolve().relative_to(REPO_ROOT))

    for s in sorted(shot_dir.glob("*.png")):
        media.append({"feature": feature, "path": rel(s), "sha256": sha256_file(s),
                      "visual_review": "pending_review", "visible_result": "", "reviewed_at": ""})
    if video_path:
        media.append({"feature": feature, "path": rel(video_path), "sha256": sha256_file(video_path),
                      "visual_review": "pending_review", "visible_result": "", "reviewed_at": ""})

    log_file = log_dir / f"{feature}-{platform}-{stamp}.log"
    log(f"log -> {log_file}")
    log_file.write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")

    identity = {
        "_comment": "macOS 已安装客户端真机验收的身份快照（现场重算，未复用历史证据）。由 tools/macos_client_accept.py 自动生成，请勿手改。",
        "kind": "macos-client-identity", "feature": feature, "platform": platform,
        "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "app_bundle": str(APP_BUNDLE), "app_executable": str(APP_EXEC),
        "build_info": build, "git_sha": app_sha, "product_version": app_version,
        "isolated_backend_port": BACKEND_PORT, "isolated_user_data": str(USER_DATA),
        "backend_health": {k: v for k, v in (api_health or {}).items() if k != "runtime"},
        "backend_health_runtime_status": ((api_health or {}).get("runtime") or {}).get("status"),
        "dmg_path": str(DMG), "dmg_sha256_this_round": sha256_file(DMG),
    }
    id_path = out / f"{feature}-{platform}-identity.json"
    id_path.write_text(json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    passed = sum(1 for c in cases if c["result"] == "passed")
    failed = sum(1 for c in cases if c["result"] == "failed")
    run = {
        "_comment": "macOS 已安装客户端真机验收记录，由 tools/macos_client_accept.py 自动生成，请勿手改。仅 media[].visual_review / visible_result / reviewed_at 可在实际查看该文件后填写。",
        "kind": "feature-acceptance", "feature": feature, "platform": platform,
        "status": "passed" if failed == 0 and passed == len(cases) and cases else "failed",
        "verdict": "PASS" if failed == 0 and passed == len(cases) and cases else "FAIL",
        "round": stamp, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "app_git_sha": app_sha, "app_version": app_version,
        "verified_at": date.today().isoformat(), "reviewed_at": "",
        "passed": passed, "failed": failed,
        "operator_observations": observations,
        "visible_content": getattr(mod, "VISIBLE_CONTENT", ""),
        "app_identity": {"app_bundle": str(APP_BUNDLE), "build_info": build,
                         "backend_health": identity["backend_health"],
                         "identity_capture": rel(id_path)},
        "media": media, "cases": cases,
    }
    artifact = {
        "_comment": "macOS 交付物台账（现场重算）：本轮重新计算 DMG 的 SHA-256，版本与 SHA 取自已安装客户端 build-info。",
        "kind": "macos-delivery-artifact", "feature": feature, "platform": platform,
        "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "release": {"version": app_version, "git_sha": app_sha,
                    "release_id": str(build.get("releaseId") or "")},
        "installed_app": {"bundle": str(APP_BUNDLE), "build_info": build},
        "artifacts": {"official_dmg": {"path": str(DMG), "sha256": sha256_file(DMG),
                                       "size_bytes": DMG.stat().st_size if DMG.is_file() else None}},
    }
    art_path = out / f"{feature}-{platform}-artifact.json"
    art_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"artifact ledger -> {art_path}")

    run_path = out / f"{feature}-{platform}-run.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"record: {run_path} status={run['status']} passed={passed} failed={failed} media={len(media)}")
    print(json.dumps({"feature": feature, "status": run["status"], "passed": passed, "failed": failed,
                      "run": str(run_path), "identity": str(id_path)}, ensure_ascii=False))
    return 0 if run["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())