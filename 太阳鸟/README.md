# 太阳鸟 PRO · 客户交付

| 文件 | 说明 |
|------|------|
| `太阳鸟-Setup-10.0.1-x64.exe` | Windows 定制安装包（企业宿主 + 考勤行业 + 太阳鸟 PRO） |
| `manifest.json` | 版本、SHA256、CI 构建记录 |
| `安装说明.txt` | 安装与首次启动说明 |
| `验收指引.txt` | Windows 验收步骤（登录→入门→装员工→一键入库→考勤转换） |

v10.0.1：修复 Windows 页面跳转/企业版误识别/报表崩溃/控制台黑窗，
智能对话「一键导入数据库」支持钉钉考勤报表（人员→人员管理、部门→客户）。

构建：merge 后在 GitHub Actions 手动触发 **Sunbird Installer**
（version=10.0.1，source_ref=main），产物 artifact `sunbird-installer`；
下载后以其 SHA256 更新 `manifest.json`。
