import os

files_to_update = [
    r'e:\FHD\README.md',
    r'e:\FHD\快速启动说明.md',
    r'e:\FHD\XCAGI\README.md',
]

for filepath in files_to_update:
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            content = content.replace('XCAGI v5.0 - AI 单据智能处理员工', 'XCAGI v6.0 - 企业 AI 员工平台')
            content = content.replace('XCAGI v4.0 AI 员工 Docker 快速启动指南', 'XCAGI v6.0 AI 员工 Docker 快速启动指南')
            content = content.replace('version=v5.0.0', 'version=v6.0.0')

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f'Updated: {filepath}')
        except Exception as e:
            print(f'Error with {filepath}: {e}')