from app.infrastructure.documents.sales_contract_generator import SalesContractGenerator
import os

template_path = r'e:\FHD\424\转 Word_扫描全能王 11.04.26 13.31.docx'
output_dir = r'e:\FHD\XCAGI\generated_contracts'

generator = SalesContractGenerator(template_path, output_dir)

result = generator.generate(
    customer_name='深圳市百木鼎家具有限公司',
    customer_phone='',
    contract_date='2026年04月11日',
    products=[{
        'model_number': '306B',
        'name': 'PU亮光硬化剂',
        'spec': '10KG×1',
        'unit': '桶',
        'quantity': '10 KG',
        'unit_price': '39.2',
        'amount': '392'
    }],
    return_buckets_expected=1,
    return_buckets_actual=0
)

print('=== 销售合同生成测试 ===')
print(f'状态: {"成功" if result["success"] else "失败"}')
print(f'文件名: {result["filename"]}')
print(f'文件存在: {os.path.exists(result["file_path"])}')
print(f'文件路径: {result["file_path"]}')
print(f'客户: {result["customer_name"]}')
print(f'日期: {result["contract_date"]}')
print(f'产品: {result["products"][0]["name"]}')
print(f'总金额: {result["total_amount"]}元')