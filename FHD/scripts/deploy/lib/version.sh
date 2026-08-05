# 版本 SSOT 出口共享函数。
# 与 scripts/dev/verify_version_anchors.py 共用 canonical_version()，唯一来源为 FHD/VERSION.md。
# 各打包/发布脚本应调用本函数获取版本，禁止在脚本里硬编码产品版本号。
#
# 用法（先 source 本文件）:
#   . "$SCRIPT_DIR/lib/version.sh"
#   VERSION="$(product_version)"   # 输出四段稳定产品版本，如 1.0.0.1

# 输出 FHD/VERSION.md 中的稳定产品版本（四段）。
product_version() {
  local src anchors mod_dir py
  src="${BASH_SOURCE[0]}"
  mod_dir="$(cd -- "$(dirname -- "$src")/../../dev" &>/dev/null && pwd)"
  anchors="$mod_dir/verify_version_anchors.py"
  py="${XCAGI_PYTHON:-python3}"
  "$py" - "$anchors" <<'PY'
import sys
from importlib.util import module_from_spec, spec_from_file_location

spec = spec_from_file_location("_verify_anchors", sys.argv[1])
mod = module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.canonical_version())
PY
}