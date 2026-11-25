<p align="center">
  <img src="docs/assets/xcagi-readme-cover.svg" alt="XCAGI 产品封面" width="100%" />
</p>

<h1 align="center">XCAGI · AI 数字生命体与企业经营平台</h1>

<p align="center">
  XCAGI 让 AI 员工在企业系统里办事，并交回可核对的结果。
</p>

<p align="center">
  <a href="https://xiu-ci.com/download"><b>官方下载</b></a> ·
  <a href="https://xiu-ci.com/">产品官网</a> ·
  <a href="FHD/docs/XCAGI-客户使用说明书.md">使用说明</a> ·
  <a href="https://xiu-ci.com/contact.html">联系与演示</a>
</p>

## 我们在做什么？

**XCAGI** 的目标定位是 AI 数字生命体与企业经营平台；宿主是数字企业操作系统。**小C** 是面向用户的稳定版数字生命体，AI 员工承担专业岗位，ERP 等业务能力由 Mod 或已授权的外部系统提供。**XCMAX** 仅为工程仓库名称。

修茈科技使用内部最新研发版本小X进行经营、研发和能力验证，经独立验收及人类发布批准后交付小C稳定版本。产品目标、100 项决策及领域术语统一见 [XCAGI 产品宪章 V1.0](specs/product-lines-3-plus-2.md)，不代表上述目标均已实现或正式发布。

完整流程仍在建设和验证，不能把代码、实验功能或候选包当成已交付能力。查已具备的功能和可用范围，请以对应版本、部署方式和账号权限为准。

## 一项业务怎么交付？

以整理考勤台账为例，这是一条我们在建设和验证的业务流程：

1. **接任务**：员工在对话里说清统计范围、业务规则和输出要求；口径不清时，小C 先问。
2. **按权限执行**：小C 读取账号有权访问的花名册和考勤表。需要审批的写入操作，等批准后才执行。
3. **核验并交付**：将结果与原表对照，把台账、异常明细和处理记录交回；没有核验过的结果不算完成。
4. **记录反馈**：把修正和异常保留下来，用于改进下一次处理和后续产品版本。

在该业务场景中，已授权 ERP 或外部业务系统提供权威记录和操作入口；小C组织任务，AI 员工负责专业执行，Mod 按场景补充工具、流程和模板。可用能力取决于部署方式、账号权限和已安装模块。

## 使用哪一端？

| 入口 | 用途 |
| --- | --- |
| **Windows / macOS 企业桌面端** | 企业业务主入口，用于处理 ERP 数据、对话派任务和使用已授权的行业 Mod。可用安装包与签名状态见[官方下载](https://xiu-ci.com/download)。 |
| **Flutter 移动端（Android / iOS）** | 现有移动查看与协作客户端源码，目标为完整功能客户端；当前功能以真实验收为准。Android 为实验渠道；iOS 是否可下载以 App Store 实际上架为准。源码或候选包不代表正式开放。 |
| **Web 平台管理端** | 用于平台运营与配置，不等同于企业桌面宿主，也不替代企业业务入口。 |

目标采用客户本地生命体与官方云端服务分离架构。模型、外部系统、模块下载或更新等可能需要联网，当前能力以实际部署、授权和验收为准。

## 从这里开始

- **安装和使用**：[官方下载](https://xiu-ci.com/download) · [客户使用说明书](FHD/docs/XCAGI-客户使用说明书.md)
- **查看源码**：[`FHD/`](FHD/) 为主要产品代码；移动端见 [`FHD/mobile-flutter-poc/`](FHD/mobile-flutter-poc/)。开发启动和仓库结构见[工程地图](docs/workmap.md)。
- **确认版本与授权**：[版本说明](FHD/VERSION.md) · [商业授权](FHD/COMMERCIAL_LICENSE.md) · [联系修茈科技](https://xiu-ci.com/contact.html)

代码编辑提案沿现有宿主数据库复用 [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) 2.0.51（MIT）及 [filelock](https://github.com/tox-dev/filelock) 4.2.4（Unlicense），保存账号、租户、工作区和原文件摘要，并协调同一文件的进程间编辑；先持久认领，再发布文件，最后消费提案，结果不确定时保留只读核对并拒绝重发。服务进程须共享数据库、工作区和数据目录。业务 JSON 保留原文，HTML 显示继续复用 [DOMPurify](https://github.com/cure53/DOMPurify) 3.4.18（Apache-2.0 或 MPL-2.0）及 Vue 文本转义。版本以现有锁文件为准。
