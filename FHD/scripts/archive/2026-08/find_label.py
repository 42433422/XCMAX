"""
使用 glob 找到文件
"""

import glob
import os

from app.utils.operational_errors import RECOVERABLE_ERRORS

# 搜索所有类似文件
files = glob.glob(r"e:\FHD\**\*PE*.png", recursive=True) + glob.glob(
    r"e:\FHD\**\*封固*.png", recursive=True
)

print("找到的文件:")
for f in files:
    print(f"  - {f}")
    print(f"    exists: {os.path.exists(f)}")

# 尝试使用其他方式
print("\n尝试列出 e:\\FHD 目录:")
try:
    for item in os.listdir(r"e:\FHD"):
        if "PE" in item or "封固" in item:
            print(f"  - {item}")
except RECOVERABLE_ERRORS as e:  # noqa: BLE001 - script boundary records arbitrary integration failures
    print(f"  错误: {e}")
