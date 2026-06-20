"""Tests for app.fastapi_app.openapi_enrichment."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from app.fastapi_app.openapi_enrichment import (
    enrich_openapi_schema,
    install_openapi_enrichment,
)


class TestEnrichOpenapiSchema:
    """Tests for enrich_openapi_schema."""

    def test_empty_schema(self) -> None:
        result = enrich_openapi_schema({})
        assert result == {}

    def test_adds_default_tags(self) -> None:
        schema: dict[str, Any] = {
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
        assert result["paths"]["/api/test"]["get"]["tags"] == ["xcagi"]

    def test_preserves_existing_tags(self) -> None:
        schema: dict[str, Any] = {
            "paths": {
                "/api/test": {
                    "get": {
                        "tags": ["custom"],
                        "summary": "Test",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        assert result["paths"]["/api/test"]["get"]["tags"] == ["custom"]

    def test_metrics_path_gets_monitoring_tag(self) -> None:
        schema: dict[str, Any] = {
            "paths": {
                "/metrics": {
                    "get": {
                        "summary": "",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        assert result["paths"]["/metrics"]["get"]["tags"] == ["monitoring"]

    def test_neurobus_path_gets_neurobus_tag(self) -> None:
        schema: dict[str, Any] = {
            "paths": {
                "/api/neurobus/events": {
                    "post": {
                        "summary": "",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        assert result["paths"]["/api/neurobus/events"]["post"]["tags"] == ["neurobus"]

    def test_adds_summary_when_missing(self) -> None:
        schema: dict[str, Any] = {
            "paths": {
                "/api/test": {
                    "get": {
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        assert result["paths"]["/api/test"]["get"]["summary"] == "GET /api/test"

    def test_preserves_existing_summary(self) -> None:
        schema: dict[str, Any] = {
            "paths": {
                "/api/test": {
                    "get": {
                        "summary": "My endpoint",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        assert result["paths"]["/api/test"]["get"]["summary"] == "My endpoint"

    def test_adds_description_from_summary(self) -> None:
        schema: dict[str, Any] = {
            "paths": {
                "/api/test": {
                    "get": {
                        "summary": "My endpoint",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        assert result["paths"]["/api/test"]["get"]["description"] == "My endpoint"

    def test_adds_200_response_schema_when_missing(self) -> None:
        schema: dict[str, Any] = {
            "paths": {
                "/api/test": {
                    "get": {
                        "summary": "Test",
                        "responses": {},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        assert "200" in result["paths"]["/api/test"]["get"]["responses"]
        resp = result["paths"]["/api/test"]["get"]["responses"]["200"]
        assert "content" in resp

    def test_metrics_gets_plain_text_response(self) -> None:
        schema: dict[str, Any] = {
            "paths": {
                "/metrics": {
                    "get": {
                        "summary": "Metrics",
                        "responses": {},
                    }
                }
            }
        }
        result = enrich_openapi_schema(schema)
        resp = result["paths"]["/metrics"]["get"]["responses"]["200"]
        assert "text/plain" in resp["content"]

    def test_skips_non_dict_path_items(self) -> None:
        schema: dict[str, Any] = {
            "paths": {
                "/api/test": "not a dict",
            }
        }
        result = enrich_openapi_schema(schema)
        assert result["paths"]["/api/test"] == "not a dict"

    def test_skips_non_http_methods(self) -> None:
        schema: dict[str, Any] = {
            "paths": {
                "/api/test": {
                    "parameters": [{"name": "id"}],
                }
            }
        }
        result = enrich_openapi_schema(schema)
        # parameters is not an HTTP method, should be skipped
        assert "parameters" in result["paths"]["/api/test"]


class TestInstallOpenapiEnrichment:
    """Tests for install_openapi_enrichment."""

    def test_installs_custom_openapi(self) -> None:
        app = FastAPI()
        original_openapi = app.openapi
        install_openapi_enrichment(app)
        assert app.openapi is not original_openapi

    def test_enriched_openapi_returns_schema(self) -> None:
        app = FastAPI()

        @app.get("/test")
        def test_endpoint() -> dict[str, str]:
            return {"hello": "world"}

        install_openapi_enrichment(app)
        schema = app.openapi()
        assert isinstance(schema, dict)
        assert "paths" in schema
        assert "/test" in schema["paths"]
