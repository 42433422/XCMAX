# XCAGI 企业版 AppGallery 提交信息

## 必须保持一致

| 项目 | 填写内容 |
| --- | --- |
| 应用名称 | XCAGI 企业版 |
| 开发者名称 | 成都修茈科技有限公司 |
| 安装后终端显示名称 | XCAGI 企业版 |
| 安装包 Bundle Name | com.xiuci.xcagi.mobile.enterprise |
| 应用图标 | 使用 `AppScope/resources/base/media/app_icon.svg` 与 `entry/src/main/resources/base/media/app_icon.svg` 同源图标 |

## 一句话简介

企业 AI 员工、协同办公与插件市场移动工作台。

## 应用介绍

XCAGI 企业版是面向企业用户的移动工作台，需要连接企业已部署的 XCAGI 后端服务使用。应用提供企业账号登录、消息会话、AI 员工协同、审批处理、通讯录、扫码配对、OCR 识别、应用市场和服务桥等功能，帮助企业员工在手机端查看任务、处理审批、发起对话并调用已安装的企业模块。

应用由成都修茈科技有限公司提供，应用内用户协议、隐私政策、关于页、安装后显示名称和 AppGallery Connect 提交信息均应使用同一应用名称与开发者名称。

## 新版本特性

1. 优化鸿蒙端应用名称、简介、应用介绍和合规信息展示。
2. 统一应用内用户协议、隐私政策、关于页中的应用名称与开发者名称。
3. 保持安装包内展示名称、启动图标和 AppGallery Connect 提交素材一致。

## 截图与视频口径

- 截图应展示真实功能：首页消息、AI 员工、审批、扫码配对、应用市场、关于页。
- 截图中的应用名称使用 `XCAGI 企业版`，公司名称使用 `成都修茈科技有限公司`。
- 不要使用 `修辞企业版`、`修茈企业版`、`XCAGI 智能科技` 等未在 AppGallery Connect 开发者信息中提交的主体名称。

## 提交前检查

1. `AppScope/resources/base/element/string.json` 的 `app_name` 为 `XCAGI 企业版`。
2. `entry/src/main/resources/base/element/string.json` 的 `app_name` 为 `XCAGI 企业版`。
3. `AppScope/app.json5` 与 `entry/src/main/module.json5` 均引用同一个 `$media:app_icon` 与 `$string:app_name`。
4. 用户协议与关于页显示 `XCAGI 企业版` 和 `成都修茈科技有限公司`。
5. AppGallery Connect 后台的应用名称、应用图标、一句话简介、应用介绍、新版本特性、截图和视频均按本文同步更新。
