"""Word extract must not use LLM scaffold path."""

from modstore_server.employee_brief_utils import extract_routing_brief
from modstore_server.txt_extract_runtime import is_txt_full_read
from modstore_server.word_extract_runtime import is_word_full_extract


def test_routing_brief_detects_word_extract_from_polluted_handoff():
    polluted = (
        "【初始想法】\n帮我做 Word 文档全量提取，输出 JSON 和 txt\n\n---\n\n"
        "【澄清对话】\n用户：...\n助手：若无疑问，将按此方案生成执行清单\n\n---\n\n"
        "【执行清单】\n1. 安装 python-docx"
    )
    rb = extract_routing_brief({"brief": polluted}, fallback=polluted)
    assert is_word_full_extract(rb)


def test_word_extract_guard_condition():
    brief = "Word docx 全量提取 JSON txt 图片 outputs/images"
    rb = extract_routing_brief({"brief": brief}, fallback=brief)
    assert is_word_full_extract(rb)


def test_txt_full_read_does_not_route_to_word():
    brief = "制作 TXT 全量读取员工包，上传 .txt 直接读取全部纯文本"
    rb = extract_routing_brief({"brief": brief}, fallback=brief)
    assert is_txt_full_read(rb)
    assert not is_word_full_extract(rb)
