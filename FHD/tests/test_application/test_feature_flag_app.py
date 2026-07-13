from __future__ import annotations

from app.application.feature_flag_app import FeatureFlagName, is_enabled


def test_feature_flag_reads_canonical_environment_name(monkeypatch):
    monkeypatch.setenv("XCAGI_FEATURE_EXPERIMENTAL_GDPR_API", "true")
    assert is_enabled(FeatureFlagName.EXPERIMENTAL_GDPR_API) is True


def test_feature_flag_uses_explicit_default(monkeypatch):
    monkeypatch.delenv("XCAGI_FEATURE_EXPERIMENTAL_GDPR_API", raising=False)
    assert is_enabled(FeatureFlagName.EXPERIMENTAL_GDPR_API, default=False) is False
    assert is_enabled(FeatureFlagName.EXPERIMENTAL_GDPR_API, default=True) is True
