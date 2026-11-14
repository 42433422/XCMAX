# Rasa NLU（可选）

运行客户端位于 [`app/ai_engines/rasa/nlu_service.py`](../app/ai_engines/rasa/nlu_service.py)。`ENABLE_RASA=0` 可关闭此能力；模型未安装或服务不可用时，客户端报告实际状态。

训练配置与领域定义维护在本目录的 `config.yml` 和 `domain.yml`。训练数据不随源码提供，调用方须提供授权的本地语料；缺少语料时命令明确失败。

从 `FHD/` 执行（需在当前 Python 环境安装 Rasa）：

```bash
python rasa/train_rasa_model.py --data /path/to/nlu.yml --output assets/rasa/models --force
```

`--config`、`--data`、`--output` 支持调用目录相对路径或绝对路径，训练失败保留非零退出码。`XCAGI/rasa/train_rasa_model.py` 转发同一实现，默认输出仍为 `XCAGI/rasa/models`。

本地模型发现顺序为 `rasa/models`、`XCAGI/rasa/models`；可用 `RASA_MODEL_PATH` 显式指定。远端模式由 `RASA_SERVER_URL` 和 `RASA_USE_SERVER=1` 配置。保留已有模型文件，迁移前不要清空兼容模型目录。
