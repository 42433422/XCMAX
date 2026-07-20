from __future__ import annotations

from scripts.autonomy import autonomy_metrics


def _summary(
    *,
    observed_days: float,
    veto_rate: float,
    total: int = 100,
    prohibited_miss: bool = False,
) -> dict[str, object]:
    veto_count = round(total * veto_rate / 100)
    return {
        "observed_days": observed_days,
        "veto_rate": veto_rate,
        "total": total,
        "veto_count": veto_count,
        "auto_pass_count": total - veto_count,
        "has_prohibited_miss": prohibited_miss,
    }


def test_window_never_passes_before_observation_period(monkeypatch) -> None:
    monkeypatch.setattr(
        autonomy_metrics,
        "summarize_autonomy_audit",
        lambda **_: _summary(observed_days=29.99, veto_rate=3.0),
    )

    report = autonomy_metrics.evaluate_window(30)

    assert report["complete"] is False
    assert report["status"] == "collecting"


def test_90_day_window_passes_only_between_one_and_five_percent(monkeypatch) -> None:
    monkeypatch.setattr(
        autonomy_metrics,
        "summarize_autonomy_audit",
        lambda **_: _summary(observed_days=90.0, veto_rate=3.0),
    )
    assert autonomy_metrics.evaluate_window(90)["status"] == "passed"

    monkeypatch.setattr(
        autonomy_metrics,
        "summarize_autonomy_audit",
        lambda **_: _summary(observed_days=90.0, veto_rate=0.5),
    )
    report = autonomy_metrics.evaluate_window(90)
    assert report["status"] == "needs_tuning"
    assert "below 1%" in str(report["status_reason"])


def test_strict_mode_fails_immediately_on_prohibited_miss(monkeypatch) -> None:
    monkeypatch.setattr(
        autonomy_metrics,
        "summarize_autonomy_audit",
        lambda **_: _summary(
            observed_days=0.1,
            veto_rate=0.0,
            total=1,
            prohibited_miss=True,
        ),
    )

    assert autonomy_metrics.main(["--days", "30", "--strict"]) == 1
