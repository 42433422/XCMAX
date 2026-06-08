# XCAGI 打包部署指南

## 概述

本文档说明如何将 XCAGI 系统打包成分发给客户的独立安装程序。

## 系统要求

- Windows 10/11 或 macOS 10.15+
- 至少 8GB RAM（AI 功能需要）
- 至少 10GB 可用磁盘空间

## 打包内容

打包后的系统包含：
- Flask 后端服务
- Vue 前端界面
- 内置 SQLite 数据库（可选 PostgreSQL）
- PyTorch + Transformers AI 模型
- 所有运行时依赖

## 打包步骤

### 方式一：使用打包脚本（Windows）

```batch
# 在项目根目录运行
build.bat
```

这将自动完成：
1. 安装前端依赖
2. 构建 Vue 前端
3. 安装 PyInstaller
4. 打包 Python 应用

### 方式二：手动打包

```bash
# 1. 构建前端
cd frontend
npm install
npm run build
cd ..

# 2. 安装 PyInstaller
pip install pyinstaller

# 3. 打包
pyinstaller xcagi.spec --clean
```

## 创建安装程序

### Windows (使用 Inno Setup)

1. 下载 Inno Setup: https://jrsoftware.org/isdl.php
2. 打开 `setup.iss`
3. 编译生成安装程序

```batch
iscc setup.iss
```

输出: `installer/XCAGI-Setup-3.0.0.exe`

## 输出目录

```
dist/
└── XCAGI/
    ├── XCAGI.exe          # 主程序
    ├── app/               # 应用资源
    ├── templates/          # 前端页面
    ├── resources/          # 资源文件
    └── data/              # 数据目录
```

## 注意事项

### 1. 体积预估

完整打包后体积约 **4-8 GB**，主要来自：
- PyTorch: ~2 GB
- Transformers: ~1 GB
- Python 运行时: ~500 MB
- 其他依赖: ~500 MB
- 应用代码: ~100 MB

### 2. AI 模型

首次启动时，AI 模型会自动下载：
- BERT 中文模型: ~400 MB
- 如果使用 DeepSeek 等云端 API，需要网络连接

### 3. 数据存储

默认使用 SQLite 数据库，数据存储在：
- Windows: `%APPDATA%\XCAGI\data\`
- macOS: `~/Library/Application Support/XCAGI/data/`

### 4. 端口要求

确保客户端电脑的 **5000 端口**未被占用。

## 故障排除

### 启动失败

1. 检查是否安装了 Visual C++ Redistributable
2. 确认 5000 端口未被占用
3. 查看日志输出

### AI 功能异常

1. 首次使用需要下载模型，确保网络连接
2. 模型文件可能被杀毒软件误杀，请添加白名单

### 前端页面空白

1. 检查 `templates/vue-dist` 目录是否存在
2. 确认前端构建成功

## 更新部署

更新时只需：
1. 重新打包新版本
2. 客户重新安装或替换文件
3. 数据文件（data/ 目录）通常可保留

## 技术支持

如遇问题，请联系技术支持。
