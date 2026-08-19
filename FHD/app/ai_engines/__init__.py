"""
AI 引擎层

提供各种 AI 模型的推理服务，包括：
- BERT 意图分类
- DeepSeek 意图识别
- RASA NLU
- 蒸馏模型
- 模型训练器
"""

from app.ai_engines import bert as _bert

BertIntentClassifier = getattr(_bert, "BertIntentClassifier", None)

__all__ = [
    "BertIntentClassifier",
]
