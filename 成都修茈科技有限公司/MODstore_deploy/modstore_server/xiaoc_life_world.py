"""Bounded, read-only forecasts of existing enterprise report metrics.

The SQL life state remains the only authority. Predictions and calibration are
advisory, never permission, KPI acceptance, or proof of causal improvement.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from statistics import fmean, median
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

Metric = Literal["intent_accuracy", "legacy_ratio", "domain_rated_ratio"]
METRICS: tuple[Metric, ...] = ("intent_accuracy", "legacy_ratio", "domain_rated_ratio")
HORIZON = timedelta(days=7)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Sample(Contract):
    observed_at: AwareDatetime
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    value: float = Field(ge=0, le=1, allow_inf_nan=False)


class Forecast(Contract):
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    training_samples: list[Sample] = Field(min_length=2, max_length=3)
    expected: float = Field(ge=0, le=1, allow_inf_nan=False)
    baseline: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def verify_training(self) -> Forecast:
        samples = self.training_samples
        if (
            self.expires_at != self.issued_at + HORIZON
            or not all(a.observed_at < b.observed_at for a, b in zip(samples, samples[1:]))
            or len({row.source_sha256 for row in samples}) != len(samples)
            or samples[-1].observed_at > self.issued_at
            or self.expected != median(row.value for row in samples)
            or self.baseline != samples[-1].value
        ):
            raise ValueError("world forecast training receipt is inconsistent")
        return self


class Evaluation(Contract):
    forecast: Forecast
    actual: Sample

    @model_validator(mode="after")
    def verify_outcome(self) -> Evaluation:
        if (
            not self.forecast.issued_at < self.actual.observed_at <= self.forecast.expires_at
            or self.actual.source_sha256 in {
                row.source_sha256 for row in self.forecast.training_samples
            }
        ):
            raise ValueError("world forecast outcome is not prospective")
        return self


class Series(Contract):
    samples: list[Sample] = Field(default_factory=list, max_length=3)
    pending: Forecast | None = None
    evaluations: list[Evaluation] = Field(default_factory=list, max_length=8)
    expired: int = Field(default=0, ge=0)


class WorldReview(Contract):
    owner_user_id: int = Field(gt=0)
    series: dict[Metric, Series] = Field(default_factory=dict)


def _sample(raw: Any, now: datetime) -> Sample | None:
    if not isinstance(raw, dict) or type(raw.get("value")) not in (int, float):
        return None
    try:
        sample = Sample.model_validate_json(json.dumps(raw, allow_nan=False))
    except (ValidationError, ValueError, TypeError):
        return None
    return sample if now - HORIZON <= sample.observed_at <= now else None


def read_samples(now: datetime) -> dict[str, dict[str, Any]]:
    """Reuse existing source readers, not model output or a second collector."""
    from modstore_server.strategy_bets import capture_metric

    result = {}
    for metric in METRICS:
        evidence = capture_metric(metric, start=now - HORIZON, end=now)
        sample = _sample(
            {
                "observed_at": evidence.get("observed_at"),
                "source_sha256": evidence.get("evidence_sha256"),
                "value": evidence.get("value"),
            },
            now,
        )
        if sample is not None:
            result[metric] = sample.model_dump(mode="json")
    return result


def advance_review(
    previous: dict[str, Any] | None, observations: dict[str, Any], *, owner: int, now: datetime
) -> dict[str, Any]:
    """Freeze forecasts before future observations; evaluate each at most once."""
    if now.utcoffset() is None or type(owner) is not int or owner <= 0:
        raise ValueError("world review requires a scoped owner and aware clock")
    review = (
        WorldReview.model_validate_json(json.dumps(previous, allow_nan=False))
        if previous and previous.get("owner_user_id") == owner
        else WorldReview(owner_user_id=owner)
    )
    for metric in METRICS:
        sample = _sample(observations.get(metric), now)
        if sample is None and metric not in review.series:
            continue
        series = review.series.setdefault(metric, Series())
        fresh = sample is not None and (
            not series.samples
            or (
                sample.observed_at > series.samples[-1].observed_at
                and all(sample.source_sha256 != old.source_sha256 for old in series.samples)
            )
        )
        pending = series.pending
        if pending is not None:
            if (
                fresh
                and sample is not None
                and pending.issued_at < sample.observed_at <= pending.expires_at
                and all(
                    sample.source_sha256 != old.source_sha256 for old in pending.training_samples
                )
            ):
                series.evaluations = [
                    *series.evaluations, Evaluation(forecast=pending, actual=sample)
                ][-8:]
                series.pending = None
            elif now >= pending.expires_at:
                series.expired += 1
                series.pending = None
        if not fresh or sample is None:
            continue
        series.samples = [*series.samples, sample][-3:]
        if series.pending is None and len(series.samples) >= 2:
            series.pending = Forecast(
                issued_at=now,
                expires_at=now + HORIZON,
                training_samples=list(series.samples),
                expected=median(row.value for row in series.samples),
                baseline=sample.value,
            )
    return review.model_dump(mode="json")


def review_projection(previous: dict[str, Any] | None, owner: Any) -> dict[str, Any]:
    """Small, same-owner summary for the next cognition cycle; not an action."""
    if not previous or type(owner) is not int or previous.get("owner_user_id") != owner:
        return {}
    review = WorldReview.model_validate_json(json.dumps(previous, allow_nan=False))
    projection = {}
    for metric, series in review.series.items():
        evaluated = series.evaluations
        row: dict[str, Any] = {
            "sample_count": len(series.samples),
            "evaluated_count": len(evaluated),
            "expired_unmeasured": series.expired,
            "status": "waiting_for_report" if series.pending else "insufficient_or_expired",
        }
        if series.pending is not None:
            pending = series.pending.model_dump(mode="json", exclude={"training_samples"})
            row["forecast"] = {
                **pending,
                "training_source_refs": [
                    item.source_sha256 for item in series.pending.training_samples
                ],
            }
        if evaluated:
            row["median_mae"] = fmean(abs(x.actual.value - x.forecast.expected) for x in evaluated)
            row["last_value_mae"] = fmean(abs(x.actual.value - x.forecast.baseline) for x in evaluated)
            row["last_actual"] = evaluated[-1].actual.model_dump(mode="json")
        projection[metric] = row
    return projection
