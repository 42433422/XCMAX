# ETL 模板测试数据

`sources/` 仅放本项目自造的输入；`expected/` 放对应的人工核对预期；`output/` 放本地生成结果，默认不提交。
`python FHD/tests/fixtures/etl_template/sources/generate.py` 可重建合成报价单；工作簿容器时间戳可能变化，以内容预期为准。
来源和许可见 `manifest.json`。客户原件、凭据和再分发许可未明确的公开下载文件不得放入仓库。
复杂冻结样本及其真值未纳入此目录，也未修改；相关私有验收需使用已授权的隔离副本。
