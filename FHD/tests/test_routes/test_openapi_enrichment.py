"""Tests for app.fastapi_app.openapi_enrichment."""
from __future__ import annotations

import pytest

from app.fastapi_app.openapi_enrichment import (
    _response_has_schema,
    enrich_openapi_schema,
    install_openapi_enrichment,
)


class TestResponseHasSchema:
    def test_no_content_returns_false(self):
        assert _response_has_schema({}) is False

    def test_none_content_returns_false(self):
        assert _response_has_schema({"content": None}) is False

    def test_empty_content_returns_false(self):
        assert _response_has_schema({"content": {}}) is False

    def test_content_with_schema_returns_true(self):
        resp = {"content": {"application/json": {"schema": {"type": "object"}}}}
        assert _response_has_schema(resp) is True

    def test_content_without_schema_returns_false(self):
        resp = {"content": {"application/json": {"description": "test"}}}
        assert _response_has_schema(resp) is False

    def test_non_dict_content_returns_false(self):
        assert _response_has_schema({"content": "invalid"}) is False


class TestEnrichOpenapiSchema:
    def test_empty_schema(self):
        result = enrich_openapi_schema({})
        assert result == {}

    def test_adds_default_tags(self):
        schema = {
            "paths": {
                "/api/test": {
                    "get": {
                        "summary": "",
                        "description": "",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        op = result["paths"]["/api/test"]["get"]
        assert op["tags"] == ["xcagi"]

    def test_metrics_path_gets_monitoring_tag(self):
        schema = {
            "paths": {
                "/metrics": {
                    "get": {
                        "summary": "",
                        "description": "",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        op = result["paths"]["/metrics"]["get"]
        assert op["tags"] == ["monitoring"]

    def test_neurobus_path_gets_neurobus_tag(self):
        schema = {
            "paths": {
                "/api/neurobus/events": {
                    "get": {
                        "summary": "",
                        "description": "",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        op = result["paths"]["/api/neurobus/events"]["get"]
        assert op["tags"] == ["neurobus"]

    def test_preserves_existing_tags(self):
        schema = {
            "paths": {
                "/api/test": {
                    "get": {
                        "tags": ["custom"],
                        "summary": "Test",
                        "description": "Test",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        assert result["paths"]["/api/test"]["get"]["tags"] == ["custom"]

    def test_adds_summary_when_missing(self):
        schema = {
            "paths": {
                "/api/test": {
                    "get": {
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        op = result["paths"]["/api/test"]["get"]
        assert op["summary"] == "GET /api/test"

    def test_adds_200_response_schema_when_missing(self):
        schema = {
            "paths": {
                "/api/test": {
                    "get": {
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        resp = result["paths"]["/api/test"]["get"]["responses"]["200"]
        assert "content" in resp

    def test_metrics_gets_plain_text_response(self):
        schema = {
            "paths": {
                "/metrics": {
                    "get": {
                        "responses": {},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        resp = result["paths"]["/metrics"]["get"]["responses"]["200"]
        assert "text/plain" in resp.get("content", {})

    def test_non_dict_path_item_skipped(self):
        schema = {"paths": {"/api/test": "not a dict"}}
        result = enrich_openapi_schema(schema)
        assert result["paths"]["/api/test"] == "not a dict"

    def test_non_http_methods_skipped(self):
        schema = {
            "paths": {
                "/api/test": {
                    "parameters": [{"name": "id"}],
                }
            }
        }
        result = enrich_openapi_schema(schema)
        assert "parameters" in result["paths"]["/api/test"]


class TestInstallOpenapiEnrichment:
    def test_installs_custom_openapi(self):
        from fastapi import FastAPI

        app = FastAPI()
        original_openapi = app.openapi
        install_openapi_enrichment(app)
        assert app.openapi is not original_openapi
