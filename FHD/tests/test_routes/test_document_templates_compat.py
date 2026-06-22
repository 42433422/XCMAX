"""Tests for app.fastapi_routes.document_templates_compat."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes.document_templates_compat import (
    _unpack_response,
    _UploadLikeFile,
    run_archive_template_analyze,
    run_archive_template_create,
    run_archive_template_update,
)


class TestUploadLikeFile:
    def test_attributes(self):
        stream = BytesIO(b"test content")
        f = _UploadLikeFile(stream, "test.xlsx", "application/vnd.ms-excel")
        assert f.filename == "test.xlsx"
        assert f.content_type == "application/vnd.ms-excel"

    def test_save(self, tmp_path):
        stream = BytesIO(b"test content")
        f = _UploadLikeFile(stream, "test.xlsx")
        dest = tmp_path / "output.xlsx"
        f.save(str(dest))
        assert dest.read_bytes() == b"test content"

    def test_save_resets_stream(self, tmp_path):
        stream = BytesIO(b"test content")
        stream.read()  # consume stream
        f = _UploadLikeFile(stream, "test.xlsx")
        dest = tmp_path / "output.xlsx"
        f.save(str(dest))
        assert dest.read_bytes() == b"test content"


class TestUnpackResponse:
    def test_dict_response_no_get_json(self):
        # A plain dict doesn't have get_json, so it falls through to the error case
        resp = {"success": True, "data": {"id": 1}}
        data, code = _unpack_response(resp)
        assert code == 500
        assert data["success"] is False

    def test_tuple_response_with_get_json(self):
        mock_resp = MagicMock()
        mock_resp.get_json.return_value = {"success": True, "data": {"id": 1}}
        mock_resp.status_code = 200
        data, code = _unpack_response((mock_resp, 200))
        assert data["success"] is True
        assert code == 200

    def test_tuple_response_without_get_json(self):
        mock_resp = MagicMock(spec=[])
        data, code = _unpack_response((mock_resp, 201))
        # No get_json method, so returns error response with code 500
        assert code == 500
        assert data["success"] is False

    def test_single_response_with_status_code(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.get_json.return_value = {"success": True}
        data, code = _unpack_response(mock_resp)
        assert code == 200

    def test_get_json_returns_non_dict(self):
        mock_resp = MagicMock()
        mock_resp.get_json.return_value = [1, 2, 3]
        mock_resp.status_code = 200
        data, code = _unpack_response(mock_resp)
        assert data == {"success": False, "message": "invalid templates response"}

    def test_single_response_no_status_code(self):
        mock_resp = MagicMock(spec=["get_json"])
        mock_resp.get_json.return_value = {"success": True}
        data, code = _unpack_response(mock_resp)
        # getattr returns default 200
        assert code == 200
        assert data["success"] is True

    def test_tuple_without_code_defaults_200(self):
        mock_resp = MagicMock()
        mock_resp.get_json.return_value = {"success": True}
        data, code = _unpack_response((mock_resp,))
        assert code == 200


class TestRunArchiveTemplateCreate:
    @patch("app.fastapi_routes.document_templates_compat._tpl")
    def test_create_with_payload(self, mock_tpl):
        mock_resp = MagicMock()
        mock_resp.get_json.return_value = {"success": True, "data": {"id": 1}}
        mock_resp.status_code = 201
        mock_tpl.create_template_with_payload.return_value = (mock_resp, 201)

        data, code = run_archive_template_create({"name": "test"})
        assert code == 201

    @patch("app.fastapi_routes.document_templates_compat._tpl")
    def test_create_with_none_payload(self, mock_tpl):
        mock_resp = MagicMock()
        mock_resp.get_json.return_value = {"success": True}
        mock_resp.status_code = 200
        mock_tpl.create_template_with_payload.return_value = (mock_resp, 200)

        data, code = run_archive_template_create(None)
        mock_tpl.create_template_with_payload.assert_called_once_with({})


class TestRunArchiveTemplateAnalyze:
    @patch("app.fastapi_routes.document_templates_compat._tpl")
    def test_analyze(self, mock_tpl):
        mock_resp = MagicMock()
        mock_resp.get_json.return_value = {"success": True, "fields": []}
        mock_resp.status_code = 200
        mock_tpl.analyze_template_with_upload.return_value = (mock_resp, 200)

        data, code = run_archive_template_analyze(
            file_body=b"fake excel content",
            filename="test.xlsx",
            template_name="Test",
        )
        assert code == 200
        mock_tpl.analyze_template_with_upload.assert_called_once()
