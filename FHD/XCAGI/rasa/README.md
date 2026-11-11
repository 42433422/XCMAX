# Rasa 兼容入口

配置与训练说明见 [`FHD/rasa`](../../rasa/README.md)。本目录只保留训练命令转发与已有 `models/` 的发现路径，不维护第二份配置。

从 `FHD/` 执行 `python XCAGI/rasa/train_rasa_model.py --data /path/to/nlu.yml`；默认模型输出仍在本目录，训练数据须由调用方提供。
