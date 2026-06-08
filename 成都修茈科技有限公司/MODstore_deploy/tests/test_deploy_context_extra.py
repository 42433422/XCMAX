"""Tests for modstore_server.deploy_context module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from modstore_server.deploy_context import (
    health_payload,
    is_production_tier,
    normalized_deploy_tier,
    resolve_git_sha,
    resolve_hostname,
)


class TestNormalizedDeployTier:
    def test_default_is_local(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MODSTORE_DEPLOY_TIER", None)
            os.environ.pop("DEPLOYMENT_ENV", None)
            assert normalized_deploy_tier() == "local"

    def test_explicit_local(self):
        with patch.dict(os.environ, {"MODSTORE_DEPLOY_TIER": "local"}):
            assert normalized_deploy_tier() == "local"

    def test_staging(self):
        with patch.dict(os.environ, {"MODSTORE_DEPLOY_TIER": "staging"}):
            assert normalized_deploy_tier() == "staging"

    def test_production(self):
        with patch.dict(os.environ, {"MODSTORE_DEPLOY_TIER": "production"}):
            assert normalized_deploy_tier() == "production"

    def test_alias_dev(self):
        with patch.dict(os.environ, {"MODSTORE_DEPLOY_TIER": "dev"}):
            assert normalized_deploy_tier() == "local"

    def test_alias_sandbox(self):
        with patch.dict(os.environ, {"MODSTORE_DEPLOY_TIER": "sandbox"}):
            assert normalized_deploy_tier() == "staging"

    def test_alias_prod(self):
        with patch.dict(os.environ, {"MODSTORE_DEPLOY_TIER": "prod"}):
            assert normalized_deploy_tier() == "production"

    def test_unknown_tier_falls_back_to_local(self):
        with patch.dict(os.environ, {"MODSTORE_DEPLOY_TIER": "bogus"}):
            assert normalized_deploy_tier() == "local"

    def test_deployment_env_fallback(self):
        with patch.dict(os.environ, {"DEPLOYMENT_ENV": "staging"}, clear=True):
            os.environ.pop("MODSTORE_DEPLOY_TIER", None)
            assert normalized_deploy_tier() == "staging"

    def test_case_insensitive(self):
        with patch.dict(os.environ, {"MODSTORE_DEPLOY_TIER": "PRODUCTION"}):
            assert normalized_deploy_tier() == "production"

    def test_whitespace_stripped(self):
        with patch.dict(os.environ, {"MODSTORE_DEPLOY_TIER": "  staging  "}):
            assert normalized_deploy_tier() == "staging"


class TestIsProductionTier:
    def test_production(self):
        with patch.dict(os.environ, {"MODSTORE_DEPLOY_TIER": "production"}):
            assert is_production_tier() is True

    def test_local(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MODSTORE_DEPLOY_TIER", None)
            assert is_production_tier() is False

    def test_staging(self):
        with patch.dict(os.environ, {"MODSTORE_DEPLOY_TIER": "staging"}):
            assert is_production_tier() is False


class TestResolveHostname:
    def test_returns_string(self):
        result = resolve_hostname()
        assert isinstance(result, str)


class TestResolveGitSha:
    def test_env_var_takes_priority(self):
        with patch.dict(os.environ, {"MODSTORE_GIT_SHA": "abc123"}):
            result = resolve_git_sha()
            assert result == "abc123"

    def test_git_sha_env_var(self):
        with patch.dict(os.environ, {"GIT_SHA": "def456"}, clear=True):
            os.environ.pop("MODSTORE_GIT_SHA", None)
            result = resolve_git_sha()
            assert result == "def456"

    def test_commit_sha_env_var(self):
        with patch.dict(os.environ, {"COMMIT_SHA": "ghi789"}, clear=True):
            os.environ.pop("MODSTORE_GIT_SHA", None)
            os.environ.pop("GIT_SHA", None)
            result = resolve_git_sha()
            assert result == "ghi789"

    def test_sha_truncated_to_64(self):
        long_sha = "a" * 100
        with patch.dict(os.environ, {"MODSTORE_GIT_SHA": long_sha}):
            result = resolve_git_sha()
            assert len(result) == 64


class TestHealthPayload:
    def test_contains_required_keys(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MODSTORE_DEPLOY_TIER", None)
            payload = health_payload()
        assert "deploy_tier" in payload
        assert "git_sha" in payload
        assert "hostname" in payload
        assert "tavily_configured" in payload

    def test_deploy_tier_value(self):
        with patch.dict(os.environ, {"MODSTORE_DEPLOY_TIER": "staging"}):
            payload = health_payload()
        assert payload["deploy_tier"] == "staging"
