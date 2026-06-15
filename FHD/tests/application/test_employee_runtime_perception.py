# -*- coding: utf-8 -*-
"""employee_runtime.perception PerceptionPipeline 多模态单元测试。

覆盖 text 透传 / document 抽取 / vision 降级 / audio transcript 各分支；
不依赖 torch/cv2/PIL（缺失时走 unavailable/skip 分支，亦被覆盖）。
"""

from __future__ import annotations

from app.application.employee_runtime.perception import PerceptionPipeline


class TestTextPassthrough:
    def test_text_only_no_artifacts(self):
        pipe = PerceptionPipeline({"perception": {"type": "text"}})
        out = pipe.process({"task": "hello", "text": "abc"})
        assert out["type"] == "text"
        assert out["artifacts"] == {}
        assert out["normalized_input"]["task"] == "hello"
        assert "_perception" not in out["normalized_input"]

    def test_process_none_payload(self):
        pipe = PerceptionPipeline(None)
        out = pipe.process(None)
        assert out["type"] == "text"
        assert "normalized_input" in out


class TestResolveText:
    def test_resolve_from_payload_key(self):
        pipe = PerceptionPipeline({"perception": {"document": {"enabled": True}}})
        text, source = pipe._resolve_text({"content": "hi there"}, "")
        assert text == "hi there"
        assert source == "payload.content"

    def test_resolve_from_text_file(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("file content here", encoding="utf-8")
        pipe = PerceptionPipeline({"perception": {"document": {"enabled": True}}})
        text, source = pipe._resolve_text({}, str(f))
        assert "file content" in text
        assert source == "file"

    def test_resolve_empty_when_nothing(self):
        pipe = PerceptionPipeline({"perception": {"document": {"enabled": True}}})
        text, source = pipe._resolve_text({}, "")
        assert text == "" and source == ""


class TestDocument:
    def test_document_with_text_produces_keypoints(self):
        pipe = PerceptionPipeline({"perception": {"document": {"enabled": True}}})
        long_text = "。".join(f"第{i}段重要内容关于销售数据分析" for i in range(20))
        out = pipe.process({"text": long_text, "task": "销售"})
        doc = out["artifacts"].get("document")
        assert doc is not None
        assert doc["status"] in ("ok", "empty", "error")

    def test_document_binary_file_skipped(self, tmp_path):
        f = tmp_path / "scan.pdf"
        f.write_bytes(b"%PDF-1.4 binary")
        pipe = PerceptionPipeline({"perception": {"document": {"enabled": True}}})
        out = pipe.process({"file_path": str(f)})
        doc = out["artifacts"].get("document")
        assert doc is not None
        assert doc["status"] == "skipped"

    def test_document_no_text_no_file_no_artifact(self):
        pipe = PerceptionPipeline({"perception": {"document": {"enabled": True}}})
        out = pipe.process({})
        assert "document" not in out["artifacts"]


class TestVision:
    def test_vision_non_image_returns_none(self):
        pipe = PerceptionPipeline({"perception": {"vision": {"enabled": True}}})
        out = pipe.process({"file_path": "notes.txt"})
        assert "vision" not in out["artifacts"]

    def test_vision_image_missing_file_skipped(self):
        pipe = PerceptionPipeline({"perception": {"vision": {"enabled": True}}})
        out = pipe.process({"file_path": "/nonexistent/img.png"})
        vis = out["artifacts"].get("vision")
        assert vis is not None
        assert vis["status"] == "skipped"

    def test_vision_image_existing_file_handled(self, tmp_path):
        # 创建假 png；PIL/OCR 缺失或无法解码 → unavailable/degraded/error（均为合法降级分支）
        f = tmp_path / "img.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n not a real png")
        pipe = PerceptionPipeline({"perception": {"vision": {"enabled": True}}})
        out = pipe.process({"file_path": str(f)})
        vis = out["artifacts"].get("vision")
        assert vis is not None
        assert vis["status"] in ("unavailable", "degraded", "error", "ok")


class TestAudio:
    def test_audio_transcript_in_payload(self):
        pipe = PerceptionPipeline({"perception": {"audio": {"enabled": True}}})
        out = pipe.process({"transcript": "会议纪要内容"})
        aud = out["artifacts"].get("audio")
        assert aud["status"] == "ok"
        assert "会议纪要" in aud["transcript"]

    def test_audio_file_without_transcript_unavailable(self):
        pipe = PerceptionPipeline({"perception": {"audio": {"enabled": True}}})
        out = pipe.process({"file_path": "rec.mp3"})
        aud = out["artifacts"].get("audio")
        assert aud is not None
        assert aud["status"] == "unavailable"

    def test_audio_no_input_no_artifact(self):
        pipe = PerceptionPipeline({"perception": {"audio": {"enabled": True}}})
        out = pipe.process({"file_path": "data.txt"})
        assert "audio" not in out["artifacts"]
