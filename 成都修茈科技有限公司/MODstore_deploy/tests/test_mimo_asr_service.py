from modstore_server.mimo_asr_service import (
    pcm16le_to_wav_bytes,
    estimate_pcm_duration_ms,
)


def test_pcm16le_to_wav_bytes_has_riff_header():
    # 100ms silence @16kHz mono s16le
    pcm = b"\x00\x00" * 1600
    wav = pcm16le_to_wav_bytes(pcm, sample_rate=16000)
    assert wav[:4] == b"RIFF"
    assert b"WAVE" in wav[:16]
    assert len(wav) > len(pcm)


def test_estimate_pcm_duration_ms():
    pcm = b"\x00\x00" * 1600
    assert estimate_pcm_duration_ms(pcm, sample_rate=16000) == 100
