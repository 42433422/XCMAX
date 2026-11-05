# 客户交付数据边界

客户交付使用通用 Enterprise 安装包和账号授权的私有 Mod。考勤原件、花名册、成本数据、客户数据库及派生输出均不属于源码，不得提交到本目录、示例包或公共市场制品。本目录仅保留这份说明。

历史目录中的客户考勤模板、花名册与人员数据库已从当前源码树移除；这不代表历史提交或已有副本被清除。真实交付数据只能保存在客户授权的私有运行目录。业务解析与转换回归使用 `tests/fixtures/synthetic_attendance` 的全合成数据。

历史 `build-sunbird-seed.py` 与 `publish-sunbird-delivery-seed.py` 入口已禁用，不会重用旧本地种子、打包或登记传入 ZIP，包括 `--zip-path`。现行私有交付 API 继续校验账号与 entitlement；服务端的 `MODSTORE_CATALOG_DIR` 必须指向操作员有权限的私有目录。新上传的员工草稿保存于 `MODSTORE_RUNTIME_DIR/employee_draft_assets/<user>/<session>`，该运行时根目录必须位于 Git checkout 之外。

默认示例模板使用明确标记的虚构数据，不可作为真实客户花名册导入生产。公共员工包不得内嵌客户固定模板。客户端初始化继续采用账号空间和已有数据优先规则，既有客户配置不会由这次源码清理覆盖。旧 Git 对象的清理需要独立的历史重写与协作者迁移。
