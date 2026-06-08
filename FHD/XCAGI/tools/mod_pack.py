#!/usr/bin/env python3
"""
MOD Packaging CLI Tool - 命令行 MOD 打包工具

用法:
    python mod_pack.py pack <mod_directory> [-o output_dir] [--no-sign]
    python mod_pack.py unpack <package_file> [-o output_dir]
    python mod_pack.py validate <package_file>
    python mod_pack.py info <package_file>
    python mod_pack.py sign <package_file> [--key private_key.pem]
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.infrastructure.mods.package import ModPackage, ModPackageError, ModSignatureError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def cmd_pack(args):
    """打包 MOD"""
    try:
        mod_path = os.path.abspath(args.mod_directory)
        
        if not os.path.isdir(mod_path):
            logger.error(f"MOD 目录不存在：{mod_path}")
            return 1
        
        manifest_path = os.path.join(mod_path, "manifest.json")
        if not os.path.isfile(manifest_path):
            logger.error(f"manifest.json 不存在：{manifest_path}")
            return 1
        
        package = ModPackage(mod_path)
        
        output_dir = args.output or os.getcwd()
        
        exclude_patterns = []
        if args.exclude:
            exclude_patterns = args.exclude.split(',')
        
        package_path = package.create_package(
            output_dir=output_dir,
            include_signature=not args.no_sign,
            private_key=args.key,
            exclude_patterns=exclude_patterns if exclude_patterns else None,
        )
        
        logger.info(f"✅ MOD 包已创建：{package_path}")
        
        if args.verify:
            logger.info("正在验证包...")
            is_valid, msg, info = package.validate_mod_package(package_path)
            if is_valid:
                logger.info(f"✅ 包验证通过：{info.get('id')} v{info.get('version')}")
            else:
                logger.error(f"❌ 包验证失败：{msg}")
                return 1
        
        return 0
        
    except ModPackageError as e:
        logger.error(f"❌ 打包失败：{e}")
        return 1
    except Exception as e:
        logger.exception("❌ 打包失败")
        return 1


def cmd_unpack(args):
    """解包 MOD"""
    try:
        package_path = os.path.abspath(args.package_file)
        
        if not os.path.isfile(package_path):
            logger.error(f"MOD 包不存在：{package_path}")
            return 1
        
        output_dir = args.output or os.getcwd()
        
        extract_path, manifest = ModPackage.extract_package(
            package_path,
            output_dir,
            verify_signature=not args.no_verify,
        )
        
        mod_id = manifest.get("id", "")
        version = manifest.get("version", "")
        
        logger.info(f"✅ MOD 包已解压：{extract_path}")
        logger.info(f"   MOD ID: {mod_id}")
        logger.info(f"   版本：{version}")
        
        return 0
        
    except ModSignatureError as e:
        logger.error(f"❌ 签名验证失败：{e}")
        return 1
    except ModPackageError as e:
        logger.error(f"❌ 解包失败：{e}")
        return 1
    except Exception as e:
        logger.exception("❌ 解包失败")
        return 1


def cmd_validate(args):
    """验证 MOD 包"""
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager
        
        package_path = os.path.abspath(args.package_file)
        
        if not os.path.isfile(package_path):
            logger.error(f"MOD 包不存在：{package_path}")
            return 1
        
        mm = get_mod_manager()
        is_valid, msg, info = mm.validate_mod_package(package_path)
        
        if is_valid:
            logger.info("✅ MOD 包验证通过")
            logger.info(f"   MOD ID: {info.get('id')}")
            logger.info(f"   名称：{info.get('name')}")
            logger.info(f"   版本：{info.get('version')}")
            logger.info(f"   作者：{info.get('author')}")
            
            if info.get('errors'):
                logger.warning(f"   警告：{info['errors']}")
            
            return 0
        else:
            logger.error(f"❌ MOD 包验证失败：{msg}")
            if info.get('errors'):
                for error in info['errors']:
                    logger.error(f"   - {error}")
            return 1
            
    except Exception as e:
        logger.exception("❌ 验证失败")
        return 1


def cmd_info(args):
    """显示 MOD 包信息"""
    try:
        package_path = os.path.abspath(args.package_file)
        
        if not os.path.isfile(package_path):
            logger.error(f"MOD 包不存在：{package_path}")
            return 1
        
        package = ModPackage(package_path)
        info = package.get_package_info()
        
        print("\n=== MOD 包信息 ===")
        print(f"ID:      {info.get('id')}")
        print(f"名称：    {info.get('name')}")
        print(f"版本：    {info.get('version')}")
        print(f"作者：    {info.get('author')}")
        print(f"描述：    {info.get('description')}")
        print(f"依赖：    {json.dumps(info.get('dependencies', {}), ensure_ascii=False, indent=2)}")
        
        manifest = package.manifest
        
        if manifest.get('backend'):
            print("\n=== 后端扩展 ===")
            print(f"入口：    {manifest['backend'].get('entry', '')}")
            print(f"初始化：  {manifest['backend'].get('init', '')}")
        
        if manifest.get('frontend'):
            print("\n=== 前端扩展 ===")
            print(f"路由：    {manifest['frontend'].get('routes', '')}")
            menu_items = manifest['frontend'].get('menu', [])
            if menu_items:
                print(f"菜单项：  {len(menu_items)} 个")
                for item in menu_items:
                    print(f"         - {item.get('label')} ({item.get('path')})")
        
        if manifest.get('hooks'):
            print("\n=== 钩子 ===")
            for event, handler in manifest['hooks'].items():
                print(f"   {event} -> {handler}")
        
        if manifest.get('comms', {}).get('exports'):
            print("\n=== 通信通道 ===")
            for channel in manifest['comms']['exports']:
                print(f"   - {channel}")
        
        if manifest.get('workflow_employees'):
            print("\n=== 工作流员工 ===")
            for emp in manifest['workflow_employees']:
                print(f"   - {emp.get('label')} ({emp.get('id')})")
        
        print()
        return 0
        
    except Exception as e:
        logger.exception("❌ 读取信息失败")
        return 1


def cmd_sign(args):
    """为 MOD 包签名"""
    try:
        package_path = os.path.abspath(args.package_file)
        
        if not os.path.isfile(package_path):
            logger.error(f"MOD 包不存在：{package_path}")
            return 1
        
        if not args.key:
            logger.error("请指定私钥文件：--key <private_key.pem>")
            return 1
        
        if not os.path.isfile(args.key):
            logger.error(f"私钥文件不存在：{args.key}")
            return 1
        
        import zipfile
        import tempfile
        import shutil
        
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(package_path, 'r') as zipf:
                zipf.extractall(temp_dir)
            
            package = ModPackage(temp_dir)
            signature = package._generate_signature(args.key)
            
            meta_inf_dir = os.path.join(temp_dir, "META-INF")
            os.makedirs(meta_inf_dir, exist_ok=True)
            
            signature_path = os.path.join(meta_inf_dir, "signature.json")
            with open(signature_path, 'w', encoding='utf-8') as f:
                json.dump(signature, f, indent=2, ensure_ascii=False)
            
            output_path = args.output or package_path
            
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
        
        logger.info(f"✅ MOD 包已签名：{output_path}")
        return 0
        
    except Exception as e:
        logger.exception("❌ 签名失败")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="MOD 打包工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    subparsers = parser.add_subparsers(dest='command', help='命令')
    
    pack_parser = subparsers.add_parser('pack', help='打包 MOD')
    pack_parser.add_argument('mod_directory', help='MOD 目录')
    pack_parser.add_argument('-o', '--output', help='输出目录')
    pack_parser.add_argument('--no-sign', action='store_true', help='不生成签名')
    pack_parser.add_argument('--key', help='私钥文件路径')
    pack_parser.add_argument('--exclude', help='排除的文件模式（逗号分隔）')
    pack_parser.add_argument('--verify', action='store_true', help='打包后验证')
    pack_parser.set_defaults(func=cmd_pack)
    
    unpack_parser = subparsers.add_parser('unpack', help='解包 MOD')
    unpack_parser.add_argument('package_file', help='MOD 包文件')
    unpack_parser.add_argument('-o', '--output', help='输出目录')
    unpack_parser.add_argument('--no-verify', action='store_true', help='不验证签名')
    unpack_parser.set_defaults(func=cmd_unpack)
    
    validate_parser = subparsers.add_parser('validate', help='验证 MOD 包')
    validate_parser.add_argument('package_file', help='MOD 包文件')
    validate_parser.set_defaults(func=cmd_validate)
    
    info_parser = subparsers.add_parser('info', help='显示 MOD 包信息')
    info_parser.add_argument('package_file', help='MOD 包文件')
    info_parser.set_defaults(func=cmd_info)
    
    sign_parser = subparsers.add_parser('sign', help='为 MOD 包签名')
    sign_parser.add_argument('package_file', help='MOD 包文件')
    sign_parser.add_argument('--key', help='私钥文件路径')
    sign_parser.add_argument('-o', '--output', help='输出文件路径')
    sign_parser.set_defaults(func=cmd_sign)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
