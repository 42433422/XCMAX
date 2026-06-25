# -*- coding: utf-8 -*-
"""
软著申请源代码文档生成器

功能：
1. 读取前后端源代码文件
2. 去除注释和空行
3. 按每页 50 行以上格式排版
4. 生成符合软著申请要求的源代码文档
"""

import os
import re
from pathlib import Path


def remove_comments_python(content: str) -> str:
    """移除 Python 代码中的注释"""
    lines = content.split('\n')
    result = []
    in_multiline_string = False
    multiline_char = None
    
    for line in lines:
        stripped = line.strip()
        
        if not stripped:
            continue
            
        if in_multiline_string:
            if multiline_char in stripped:
                in_multiline_string = False
            continue
            
        if stripped.startswith('"""') or stripped.startswith("'''"):
            multiline_char = stripped[:3]
            if stripped.count(multiline_char) >= 2 and len(stripped) > 3:
                continue
            in_multiline_string = True
            continue
            
        if '#' in line:
            code_part = line.split('#')[0]
            if code_part.strip():
                result.append(code_part.rstrip())
        else:
            result.append(line.rstrip())
    
    return '\n'.join(result)


def remove_comments_vue(content: str) -> str:
    """移除 Vue 文件中的注释"""
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    return content


def remove_comments_ts(content: str) -> str:
    """移除 TypeScript/JavaScript 代码中的注释"""
    content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    return content


def remove_empty_lines(content: str) -> str:
    """移除空行"""
    lines = content.split('\n')
    result = [line for line in lines if line.strip()]
    return '\n'.join(result)


def process_file(file_path: str) -> str:
    """处理单个文件，去除注释和空行"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == '.py':
        content = remove_comments_python(content)
    elif ext == '.vue':
        content = remove_comments_vue(content)
    elif ext in ['.ts', '.js']:
        content = remove_comments_ts(content)
    
    content = remove_empty_lines(content)
    return content


def generate_source_code_doc(source_dir: str, output_file: str, file_patterns: list):
    """生成源代码文档"""
    all_code = []
    file_count = 0

    # 这些目录不进软著
    skip_dirs = {
        '__pycache__', '.git', '.svn', 'node_modules', 'dist', 'build',
        '.next', '.nuxt', '.cache', '.venv', 'venv', 'env', '.mypy_cache',
        '.pytest_cache', '.ruff_cache', 'htmlcov', 'coverage', '.idea',
        '.vscode', 'site-packages', '.eggs',
    }
    # 软著申请目录自己、生成产物目录、备份目录也排除
    skip_dirs.update({'软著申请', 'generated_contracts', 'examples'})

    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]

        for file in files:
            if any(file.endswith(p) for p in file_patterns):
                file_path = os.path.join(root, file)
                try:
                    code = process_file(file_path)
                    if code.strip():
                        rel_path = os.path.relpath(file_path, source_dir)
                        all_code.append(f"// 文件：{rel_path}")
                        all_code.append(code)
                        all_code.append("")
                        file_count += 1
                        if file_count % 50 == 0:
                            print(f"  已处理 {file_count} 个文件...")
                except Exception as e:
                    print(f"  ! 处理失败 {file_path}: {e}")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(all_code))

    print(f"\n生成完成：共 {file_count} 个文件 → {output_file}")


if __name__ == '__main__':
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    # 软著申请目录在 FHD/XCAGI/软著申请/，代码库根在 FHD/
    code_root = os.path.dirname(os.path.dirname(here))
    output_dir = here

    os.makedirs(output_dir, exist_ok=True)

    print("=== 软著申请源代码文档生成器 ===")
    print(f"代码根目录：{code_root}")
    print(f"输出目录：{output_dir}\n")

    print("正在生成前端源代码文档...")
    frontend_dir = os.path.join(code_root, 'frontend', 'src')
    frontend_output = os.path.join(output_dir, '前端源代码.txt')

    frontend_patterns = ['.vue', '.ts', '.js']
    if not os.path.isdir(frontend_dir):
        print(f"  ! 找不到前端目录：{frontend_dir}，跳过")
    else:
        generate_source_code_doc(frontend_dir, frontend_output, frontend_patterns)

    print("\n正在生成后端源代码文档...")
    backend_dir = os.path.join(code_root, 'app')
    backend_output = os.path.join(output_dir, '后端源代码.txt')

    backend_patterns = ['.py']
    if not os.path.isdir(backend_dir):
        print(f"  ! 找不到后端目录：{backend_dir}，跳过")
    else:
        generate_source_code_doc(backend_dir, backend_output, backend_patterns)

    print("\n所有文档生成完成！")
    print(f"输出目录：{output_dir}")
