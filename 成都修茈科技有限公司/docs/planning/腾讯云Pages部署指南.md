# 腾讯云 Pages 部署指南

## 📋 部署方案概述

**腾讯云 Pages**：无服务器静态网站托管服务
- **零配置**：无需手动配置服务器、CDN、SSL证书
- **自动部署**：关联代码仓库后自动构建和部署
- **全球加速**：自动部署到 EO 全球节点
- **免费额度**：每月免费 100GB 流量
- **HTTPS支持**：自动配置 SSL 证书

## 🚀 部署步骤

### 方法一：通过代码仓库部署（推荐）

#### 第一步：创建 Git 仓库

1. **初始化本地仓库**
   ```bash
   cd "E:\成都修茈科技有限公司"
   git init
   git add .
   git commit -m "Initial commit"
   ```

2. **推送到远程仓库**
   - **GitHub**：创建新仓库，然后推送
   - **GitLab**：创建新仓库，然后推送
   - **Gitee**：创建新仓库，然后推送（推荐国内用户）

   ```bash
   # GitHub 示例
   git remote add origin https://github.com/你的用户名/仓库名.git
   git branch -M main
   git push -u origin main
   ```

#### 第二步：创建 Pages 应用

1. **进入 Pages 控制台**
   - 登录腾讯云控制台
   - 搜索"静态网站托管"或"Pages"
   - 进入 Pages 控制台

2. **创建新应用**
   - 点击"新建应用"
   - **框架**：选择"静态网站"或"自定义"
   - **代码源**：选择你的代码仓库（GitHub/GitLab/Gitee）
   - **分支**：选择 main 或 master
   - **构建目录**：留空（根目录）
   - 点击"创建"

3. **等待部署完成**
   - 系统会自动构建和部署
   - 通常需要 1-3 分钟
   - 部署完成后会提供访问地址

### 方法二：通过手动上传部署

#### 第一步：准备文件

1. **确保文件结构正确**
   ```
   E:\成都修茈科技有限公司\
   ├── index.html
   ├── about.html
   ├── services.html
   ├── solutions.html
   ├── cases.html
   ├── news.html
   ├── contact.html
   ├── honors.html
   ├── case-*.html
   ├── styles.css
   ├── main.js
   ├── activities.json
   ├── news.json
   ├── assets\
   │   └── brand-logo.svg
   └── uploads\
       ├── activity_banner_1.svg
       ├── activity_banner_2.svg
       └── activity_banner_3.svg
   ```

2. **压缩文件**
   - 将所有文件压缩为 zip 格式
   - 确保包含 uploads 文件夹

#### 第二步：创建 Pages 应用

1. **进入 Pages 控制台**
   - 登录腾讯云控制台
   - 搜索"静态网站托管"或"Pages"
   - 进入 Pages 控制台

2. **创建新应用**
   - 点击"新建应用"
   - **部署方式**：选择"手动上传"
   - **应用名称**：输入应用名称（如：xiuzai-website）
   - **上传文件**：选择压缩的 zip 文件
   - 点击"创建"

3. **等待部署完成**
   - 系统会自动解压和部署
   - 通常需要 1-2 分钟

### 第三步：配置自定义域名

1. **添加域名**
   - 进入 Pages 应用详情
   - 点击"设置" → "自定义域名"
   - 点击"添加域名"
   - 输入你的域名（如：www.xiuzai.com）

2. **配置 DNS**
   - 获取 CNAME 记录
   - 到域名 DNS 管理处添加 CNAME 记录
   - 等待 DNS 生效（通常 10 分钟 - 24 小时）

3. **SSL 证书**
   - Pages 会自动申请和配置 SSL 证书
   - 无需手动操作

### 第四步：测试访问

1. **测试默认域名**
   - 访问：`https://应用名.pages.tencent-cloud.com`

2. **测试自定义域名**
   - 访问：`https://你的域名`

3. **检查功能**
   - 测试所有页面链接
   - 检查图片和资源加载
   - 测试移动端显示

## 🔄 持续部署（推荐）

### 自动更新流程

1. **修改本地文件**
   - 编辑网站内容
   - 添加新功能

2. **提交代码**
   ```bash
   git add .
   git commit -m "Update website"
   git push
   ```

3. **自动部署**
   - Pages 检测到代码更新
   - 自动构建和部署
   - 通常 1-3 分钟完成

### 配置 Webhook（可选）

1. **获取 Webhook URL**
   - 进入 Pages 应用设置
   - 找到 Webhook 配置
   - 复制 Webhook URL

2. **配置仓库 Webhook**
   - 在代码仓库设置中添加 Webhook
   - 粘贴 Webhook URL
   - 选择触发事件（push）

## 💰 成本估算

### 免费额度
- **流量**：每月 100GB
- **构建次数**：每月 500 次
- **存储**：1GB

### 付费套餐
- **基础版**：9.9元/月
  - 流量：500GB
  - 构建：1000次
  - 存储：5GB

- **专业版**：49.9元/月
  - 流量：2TB
  - 构建：5000次
  - 存储：20GB

### 预估费用（小型企业网站）
- **免费额度**：通常足够使用
- **如超出**：基础版 9.9元/月

## 🔧 高级配置

### 1. 自定义 404 页面

1. **创建 404.html**
   ```html
   <!DOCTYPE html>
   <html>
   <head>
       <meta charset="UTF-8">
       <title>页面未找到</title>
   </head>
   <body>
       <h1>404 - 页面未找到</h1>
       <p>抱歉，您访问的页面不存在。</p>
       <a href="/">返回首页</a>
   </body>
   </html>
   ```

2. **上传到项目根目录**
   - 将 404.html 放在项目根目录
   - 重新部署

### 2. 环境变量

1. **添加环境变量**
   - 进入 Pages 应用设置
   - 找到环境变量配置
   - 添加需要的变量

2. **在代码中使用**
   ```javascript
   const apiUrl = process.env.API_URL || 'default-api-url';
   ```

### 3. 重定向规则

1. **创建 _redirects 文件**
   ```
   /old-page.html /new-page.html 301
   /blog/* /articles/:splat 301
   ```

2. **上传到项目根目录**
   - 将 _redirects 文件放在项目根目录
   - 重新部署

### 4. 自定义 Headers

1. **创建 _headers 文件**
   ```
   /*
     X-Frame-Options: DENY
     X-Content-Type-Options: nosniff
     Referrer-Policy: strict-origin-when-cross-origin
   ```

2. **上传到项目根目录**
   - 将 _headers 文件放在项目根目录
   - 重新部署

## 📝 维护建议

### 定期更新
- 修改内容后直接提交代码
- Pages 会自动部署更新

### 监控访问
- 在 Pages 控制台查看访问统计
- 监控流量使用情况

### 备份代码
- 定期备份 Git 仓库
- 使用 GitHub/GitLab/Gitee 的版本控制

## 🆘 常见问题

### 1. 部署失败
- 检查代码仓库是否正确连接
- 检查构建配置是否正确
- 查看部署日志了解错误详情

### 2. 页面无法访问
- 检查部署状态是否为"运行中"
- 检查自定义域名 DNS 配置
- 等待 DNS 生效

### 3. 图片无法加载
- 检查文件路径是否正确
- 检查 uploads 文件夹是否上传
- 检查文件名大小写

### 4. 更新后没有生效
- 检查代码是否成功推送
- 等待自动部署完成
- 清除浏览器缓存

### 5. 超出免费额度
- 升级到付费套餐
- 优化网站资源大小
- 使用 CDN 缓存

### 6. EdgeOne（`*.edgeone.cool`）与本地 `http://127.0.0.1:9999` 不一致

- **本地 9999**：运行 `python app.py`（Flask），读当前工程文件，并有 `/api/*`、`/admin`。
- **Pages / EdgeOne**：只下发已部署的静态文件，**不会跑 Flask**；新闻与活动依赖根目录的 `activities.json`、`news.json` 和 `uploads/`。
- **对齐方式**：推送或上传**整站**（含 `assets/`），部署完成后在控制台**刷新缓存**；需要后台管理时需单独部署 Python 服务。

## 📞 技术支持

- **腾讯云 Pages 文档**：https://cloud.tencent.com/document/product/1552
- **Pages 控制台**：https://console.cloud.tencent.com/pages
- **工单系统**：腾讯云控制台 → 工单系统
- **技术社区**：https://cloud.tencent.com/developer

## 🎯 快速部署检查清单

- [ ] 准备网站文件
- [ ] 创建 Git 仓库（推荐）
- [ ] 推送到远程仓库（GitHub/GitLab/Gitee）
- [ ] 在 Pages 控制台创建应用
- [ ] 关联代码仓库或上传文件
- [ ] 等待部署完成
- [ ] 测试默认域名访问
- [ ] 配置自定义域名
- [ ] 配置 DNS 解析
- [ ] 测试自定义域名访问
- [ ] 配置持续部署（可选）

---

**部署完成后，你的企业门户网站就可以通过 https://你的域名 访问了！**