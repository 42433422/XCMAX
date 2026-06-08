from modstore_server.voice_s2s_sentence import VoiceStreamSentenceSplitter


def test_splitter_emits_complete_sentences():
    sp = VoiceStreamSentenceSplitter(early_clause=False, first_chunk_len=20)
    chunks = []
    chunks.extend(sp.feed("这是第一句。"))
    chunks.extend(sp.feed("这是第一句。这是第二句。"))
    tail = sp.finish("这是第一句。这是第二句。")
    chunks.extend(tail)
    text = "".join(chunks)
    assert "第一句" in text
    assert "第二句" in text or not tail


def test_splitter_does_not_emit_incomplete_tail():
    sp = VoiceStreamSentenceSplitter(early_clause=False, first_chunk_len=0)
    assert sp.feed("这是第一句。第二句还没说完") == ["这是第一句。"]
    assert sp.finish("这是第一句。第二句还没说完") == ["第二句还没说完"]


def test_splitter_does_not_hard_cut_mid_phrase():
    sp = VoiceStreamSentenceSplitter(early_clause=False, first_chunk_len=9)
    assert sp.feed("这是一段没有自然停顿但已经很长的回答") == []


def test_splitter_emits_natural_early_clause():
    sp = VoiceStreamSentenceSplitter(
        early_clause=True,
        early_clause_min_len=8,
        first_chunk_len=0,
    )
    assert sp.feed("这是一段足够长的停顿，后面继续") == ["这是一段足够长的停顿，"]
