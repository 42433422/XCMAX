"""Stable trigger vocabulary and output contracts for TXT employee packs."""

TXT_DOC_KEYWORDS = (".txt", "txt", "纯文本", "文本文件", "text file", "plain text")
TXT_READ_ACTION_KEYWORDS = ("读取", "读出", "全量", "读入", "read", "load", "提取", "解析")
TXT_GENERATE_ACTION_KEYWORDS = (
    "生成",
    "写入",
    "写文档",
    "写 txt",
    "写txt",
    "输出",
    "改写",
    "润色",
    "write",
    "generate",
    "json",
    "结构化",
)
TXT_GENERATE_EXCLUDE = ("仅读取", "只读", "原样", "不要生成", "read only")
TXT_READ_OUTPUT_FIELDS = ("plain_text", "encoding", "line_count", "char_count", "source")
TXT_GENERATE_OUTPUT_FIELDS = ("lines", "paragraphs", "plain_text", "stats", "metadata")

__all__ = [
    "TXT_DOC_KEYWORDS",
    "TXT_GENERATE_ACTION_KEYWORDS",
    "TXT_GENERATE_EXCLUDE",
    "TXT_GENERATE_OUTPUT_FIELDS",
    "TXT_READ_ACTION_KEYWORDS",
    "TXT_READ_OUTPUT_FIELDS",
]
