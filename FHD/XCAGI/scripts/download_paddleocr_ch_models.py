#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载与当前 XCAGI（PaddleOCR 3.x + PaddleX）兼容的中文 OCR 推理模型到本地。

来源：百度 BOS「PaddleX 官方推理模型」paddle3.0.0（含 inference.yml，可完全离线）。

解压后目录结构（与 XCAGI_PADDLE_MODEL_ROOT 约定一致）：

  <目标目录>/
    PP-OCRv4_mobile_det_infer/
    PP-OCRv4_mobile_rec_infer/

说明：关闭文档预处理与文字行方向分类，避免再拉取其它模型；倾斜文本效果可能略弱于在线全量管线。

用法:

  python scripts/download_paddleocr_ch_models.py
  python scripts/download_paddleocr_ch_models.py --dir D:\\models\\paddleocr

完成后设置环境变量并重启 XCAGI：

  $env:XCAGI_PADDLE_MODEL_ROOT="D:\\models\\paddleocr"
"""

from __future__ import annotations

import argparse
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

# PaddleX 官方推理包（与 paddleocr 3.x 加载逻辑一致）
BOS_BASE = (
    "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/"
)
MODELS = [
    ("PP-OCRv4_mobile_det_infer.tar", f"{BOS_BASE}PP-OCRv4_mobile_det_infer.tar"),
    ("PP-OCRv4_mobile_rec_infer.tar", f"{BOS_BASE}PP-OCRv4_mobile_rec_infer.tar"),
]


def download_file(url: str, dest: Path, chunk: int = 1024 * 256) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "XCAGI-paddleocr-download/1.1"})
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as out:
        while True:
            b = resp.read(chunk)
            if not b:
                break
            out.write(b)


def extract_tar(tar_path: Path, dest_dir: Path) -> None:
    with tarfile.open(tar_path, "r:*") as tf:
        tf.extractall(path=dest_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 PaddleOCR 中文推理模型（PaddleX 格式，可离线）")
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="解压目标目录（默认：XCAGI/paddleocr_local_models）",
    )
    parser.add_argument("--keep-tar", action="store_true", help="保留 .tar 文件")
    args = parser.parse_args()

    xcagi_root = Path(__file__).resolve().parents[1]
    target = args.dir or (xcagi_root / "paddleocr_local_models")
    target = target.resolve()
    cache = target / "_downloads"
    cache.mkdir(parents=True, exist_ok=True)

    print(f"目标目录: {target}")
    for fname, url in MODELS:
        tar_path = cache / fname
        if not tar_path.is_file():
            print(f"下载: {fname} ...")
            try:
                download_file(url, tar_path)
            except Exception as e:
                print(f"失败: {fname} -> {e}", file=sys.stderr)
                return 1
        else:
            print(f"已存在缓存: {tar_path}")

        print(f"解压: {fname} -> {target}")
        try:
            extract_tar(tar_path, target)
        except Exception as e:
            print(f"解压失败: {e}", file=sys.stderr)
            return 1

        if not args.keep_tar:
            try:
                tar_path.unlink()
            except OSError:
                pass

    expected = [
        target / "PP-OCRv4_mobile_det_infer",
        target / "PP-OCRv4_mobile_rec_infer",
    ]
    for p in expected:
        yml = p / "inference.yml"
        if not yml.is_file():
            print(f"错误: 未找到 {yml}", file=sys.stderr)
            return 1

    root_str = str(target)
    if os.name == "nt" and Path(target).drive:
        print("\nPowerShell（当前会话）:")
        print(f'  $env:XCAGI_PADDLE_MODEL_ROOT = "{root_str}"')
    else:
        print("\nBash（当前会话）:")
        print(f'  export XCAGI_PADDLE_MODEL_ROOT="{root_str}"')

    print("\n重启 XCAGI 后 OCR 将仅从上述目录加载 PP-OCRv4 mobile det/rec（无需 HuggingFace）。")
    print("若你曾用旧脚本下载过 ch_PP-OCRv4_*（无 inference.yml），请删除旧目录后重新运行本脚本。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
