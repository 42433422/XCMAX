# 客户交付数据边界

客户交付使用通用 Enterprise 安装包和账号授权的私有 Mod。考勤原件、花名册、成本数据、客户数据库及派生输出均不属于源码，不得提交到本目录、示例包或公共市场制品。历史原件已按文件哈希归档；本目录仅保留这份说明。

种子构建工具要求显式指定版本库之外的私有目录：

```bash
python scripts/package/build-sunbird-seed.py --seed-root /private/customer-seed --template-src /private/input/attendance.xlsx
python scripts/package/publish-sunbird-delivery-seed.py --seed-root /private/customer-seed --out-dir /private/build --catalog-dir /private/catalog
```

示例路径必须替换为操作员有权限的目录。服务端的 `MODSTORE_CATALOG_DIR` 应指向同一私有 catalog；下载仍执行账号与 entitlement 校验。新上传的员工草稿保存于 `MODSTORE_RUNTIME_DIR/employee_draft_assets/<user>/<session>`，该运行时根目录必须位于 Git checkout 之外。

测试只使用合成数据，公共员工包不得内嵌客户固定模板。客户端初始化继续采用账号空间和已有数据优先规则，既有客户配置不会由这次源码清理覆盖。删除当前分支中的文件不等于清除 Git 历史；旧对象的清理需要独立的历史重写与协作者迁移。
