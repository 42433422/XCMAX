# mypy: disable-error-code="arg-type, union-attr"
"""
冒烟测试：验证后端 OCR 提取功能
"""

# 直接导入模块文件
import importlib.util

from app.utils.operational_errors import RECOVERABLE_ERRORS

spec = importlib.util.spec_from_file_location(
    "label_template_generator",
    r"E:\FHD\XCAGI\app\services\skills\label_template_generator\label_template_generator.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

extract_text_with_ocr = module.extract_text_with_ocr

# 测试图片
test_images = [
    r"e:\FHD\26-0300001A_第1项_PE白底漆.png",
    r"e:\FHD\26-0300001A_第1项_PE封固底漆稀料.png",
]

for image_path in test_images:
    filename = image_path.split("\\")[-1]
    print("\n" + "=" * 70)
    print(f"测试：{filename}")
    print("=" * 70)

    try:
        result = extract_text_with_ocr(image_path)

        if result.get("success"):
            print("✓ 成功")
            print(f"  识别到 {result.get('total_blocks', 0)} 个文本块")
            print(f"  识别到 {len(result.get('fields', []))} 个字段")

            grid = result.get("grid", {})
            print(f"  网格：{grid.get('rows', 0)} 行 × {grid.get('cols', 0)} 列")

            fields = result.get("fields", [])
            for i, field in enumerate(fields[:5]):
                print(f"    字段{i + 1}: {field.get('label')} = {field.get('value')}")
        else:
            print(f"✗ 失败：{result.get('error')}")

    except RECOVERABLE_ERRORS as e:  # noqa: BLE001 - script boundary records arbitrary integration failures
        print(f"✗ 异常：{e}")
        import traceback

        traceback.print_exc()

print("\n\n✓ 冒烟测试完成")
