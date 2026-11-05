# 太阳鸟考勤员

这是一个用于测试“做员工”生成能力的 `employee_pack` 答案包。它把太阳鸟考勤转换程序内置到员工包中，封装成纯 Python 脚本型员工：

- `rules`：直接导入 `taiyangniao_attendance.rules` 返回规则摘要
- `convert`：直接调用 `taiyangniao_attendance.convert.convert_attendance_file`
- `echo/help`：离线测试与输入说明

员工包内置 `backend/vendor/taiyangniao_attendance` 和仅供回归演示的全合成默认模板 `backend/templates/synthetic/attendance-template.xlsx`，模板使用 `SYNTHETIC-*` 虚构人员，禁止直接作为真实客户花名册导入生产。部署后不再要求服务器额外存在 `taiyangniao-pro` 目录、配置 `TAIYANGNIAO_BACKEND_PATH`，或在工作目录预置默认模板。

## 测试输入

```json
{
  "action": "convert",
  "file_path": "uploads/dingtalk-attendance.xlsx",
  "output_relpath": "424/考勤转换输出.xlsx",
  "template_relpath": "synthetic/attendance-template.xlsx",
  "use_personnel_roster": true,
  "workspace_root": "e:/FHD"
}
```

如果只想验证脚本是否能导入规则：

```json
{
  "action": "rules"
}
```

## 私有输入

本示例只保留员工实现与包定义。运行时由获授权的账号提供考勤模板，客户原件及其花名册不得加入示例或公共员工包。历史含客户数据的 `.xcemp` 已撤出源码 catalog；私有交付由受控运行时重新构建并授权下载。
