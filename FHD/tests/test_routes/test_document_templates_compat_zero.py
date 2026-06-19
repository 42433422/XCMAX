"""Tests for app.fastapi_routes.document_templates_compat."""
from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes.document_templates_compat import (
    _UploadLikeFile,
    _unpack_response,
    run_archive_template_analyze,
    run_archive_template_create,
    run_archive_template_update,
)


class TestUploadLikeFile:
    """Tests for _UploadLikeFile."""

    def test_attributes(self) -> None:
        stream = BytesIO(b"hello")
        f = _UploadLikeFile(stream, "test.xlsx", "application/vnd.ms-excel")
        assert f.filename == "test.xlsx"
        assert f.content_type == "application/vnd.ms-excel"
        assert f.stream is stream

    def test_default_content_type(self) -> None:
        stream = BytesIO(b"data")
        f = _UploadLikeFile(stream, "file.bin")
        assert f.content_type == "application/octet-stream"

    def test_save_writes_to_file(self, tmp_path: object) -> None:
        from pathlib import Path
        tmp = tmp_path  # type: Path
        stream = BytesIO(b"file content here")
        f = _UploadLikeFile(stream, "test.bin")
        dst = str(tmp / "output.bin")
        f.save(dst)
        with open(dst, "rb") as fp:
            assert fp.read() == b"file content here"


class TestUnpackResponse:
    """Tests for _unpack_response.

    _unpack_response only extracts data from objects that have a get_json() method
    (duck-typed Starlette Response). Plain dicts and tuples of dicts fall through
    to the error return because dicts don't have get_json().
    """

    def test_dict_response_falls_through_to_error(self) -> None:
        # A plain dict does not have get_json(), so it returns the error fallback
        data, code = _unpack_response({"success": True, "data": "ok"})
        assert data["success"] is False
        assert code == 500

    def test_tuple_with_dict_falls_through_to_error(self) -> None:
        # Tuple of (dict, code): dict doesn't have get_json(), so error return
        # Note: the code extracted from tuple is NOT used in the error return;
        # the function always returns 500 in the error case.
        data, code = _unpack_response(({"success": True}, 201))
        assert data["success"] is False
        assert code == 500

    def test_tuple_with_single_element(self) -> None:
        data, code = _unpack_response(({"success": True},))
        assert data["success"] is False
        assert code == 500

    def test_response_object_with_get_json(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.get_json.return_value = {"success": True, "data": "from_json"}
        data, code = _unpack_response(resp)
        assert data == {"success": True, "data": "from_json"}
        assert code == 200

    def test_response_object_with_non_dict_json(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.get_json.return_value = [1, 2, 3]  # not a dict
        data, code = _unpack_response(resp)
        assert data["success"] is False

    def test_response_object_without_get_json(self) -> None:
        resp = MagicMock(spec=[])  # no get_json attribute
        resp.status_code = 200
        data, code = _unpack_response(resp)
        assert data["success"] is False

    def test_response_with_none_status_code(self) -> None:
        resp = MagicMock()
        resp.status_code = None
        resp.get_json = MagicMock(return_value=None)
        data, code = _unpack_response(resp)
        # get_json returns None (not a dict), so falls through to error
        assert code == 500

    def test_tuple_with_response_object(self) -> None:
        # Tuple of (response_object, code)
        resp = MagicMock()
        resp.get_json.return_value = {"success": True}
        data, code = _unpack_response((resp, 201))
        assert data["success"] is True
        assert code == 201


class TestRunArchiveTemplateCreate:
    """Tests for run_archive_template_create."""

    def test_calls_create_with_payload(self) -> None:
        mock_tpl = MagicMock()
        # Return a response object with get_json that returns a dict
        mock_resp = MagicMock()
        mock_resp.get_json.return_value = {"success": True}
        mock_resp.status_code = 201
        mock_tpl.create_template_with_payload.return_value = (mock_resp, 201)
        with patch("app.fastapi_routes.document_templates_compat._tpl", mock_tpl):
            data, code = run_archive_template_create({"name": "test"})
            assert data["success"] is True
            assert code == 201

    def test_handles_none_payload(self) -> None:
        mock_tpl = MagicMock()
        mock_resp = MagicMock()
        mock_resp.get_json.return_value = {"success": True}
        mock_resp.status_code = 200
        mock_tpl.create_template_with_payload.return_value = (mock_resp, 200)
        with patch("app.fastapi_routes.document_templates_compat._tpl", mock_tpl):
            data, code = run_archive_template_create(None)
            mock_tpl.create_template_with_payload.assert_called_with({})


class TestRunArchiveTemplateUpdate:
    """Tests for run_archive_template_update."""

    def test_calls_update_with_payload(self) -> None:
        mock_tpl = MagicMock()
        mock_resp = MagicMock()
        mock_resp.get_json.return_value = {"success": True}
        mock_resp.status_code = 200
        mock_tpl.update_template_with_payload.return_value = (mock_resp, 200)
        with patch("app.fastapi_routes.document_templates_compat._tpl", mock_tpl):
            data, code = run_archive_template_update({"id": 1})
            assert data["success"] is True


class TestRunArchiveTemplateAnalyze:
    """Tests for run_archive_template_analyze."""

    def test_calls_analyze_with_upload(self) -> None:
        mock_tpl = MagicMock()
        mock_resp = MagicMock()
        mock_resp.get_json.return_value = {"success": True}
        mock_resp.status_code = 200
        mock_tpl.analyze_template_with_upload.return_value = (mock_resp, 200)
        with patch("app.fastapi_routes.document_templates_compat._tpl", mock_tpl):
            data, code = run_archive_template_analyze(
                file_body=b"file content",
                filename="test.xlsx",
                template_name="Test Template",
                template_scope="global",
            )
            assert data["success"] is True
            mock_tpl.analyze_template_with_upload.assert_called_once()
            call_args = mock_tpl.analyze_template_with_upload.call_args
            upload_file = call_args[0][0]
            assert isinstance(upload_file, _UploadLikeFile)
            assert upload_file.filename == "test.xlsx"
