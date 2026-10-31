"""Pure correction contracts: no model, database, customer data or fixture I/O."""

import json
from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.application.elt.catalog_price_history import (
    effective_history,
    effective_price,
    history_events,
    manual_provenance,
    validate_correction,
)
from app.application.elt.errors import EltConflict, EltError

JAN = (date(2026, 1, 1), date(2026, 2, 1))
FEB = (date(2026, 2, 1), date(2026, 3, 1))


def observation(index, price="10.00", period=JAN, *, supersedes=None):
    row = SimpleNamespace(
        id=index,
        tenant_id=5,
        product_id=11,
        owner_user_id=7,
        source_key=f"{index:064x}",
        price=Decimal(price),
        period_start=period[0],
        period_end=period[1],
        period_label="unmarked" if period[0] is None else str(period[0]),
        provenance_json=json.dumps([{"kind": "imported", "cell": "A1"}]),
    )
    if supersedes is not None:
        row.provenance_json = json.dumps(
            {
                "kind": "catalog_price_v1",
                "operation_id": str(UUID(int=index)),
                "run_id": f"run_{index}",
                "reason": "Correct the explicitly reviewed amount",
                "supersedes": [item.source_key for item in supersedes],
                "currency": "CNY",
                "price_unit": "kg",
                "actor_id": "7",
                "receipt_key": "catalog-price-receipt-v1:" + f"{index:064x}",
            }
        )
    return row


def trust(row, envelope):
    # An explicit fixture receipt verifier, not the production verification boundary.
    return envelope["receipt_key"].endswith(row.source_key)


def current(rows):
    active = effective_history(rows, verify_manual=trust)
    return effective_price(history_events(active))


def test_repeat_same_period_correction_retains_original_images_and_trusts_entire_chain():
    first = observation(1)
    second = observation(2, "12.00", supersedes=[first])
    third = observation(3, "11.00", supersedes=[second])
    rows = [first, second, third]
    originals = deepcopy([vars(row) for row in rows])
    verified = []

    def verify(row, envelope):
        verified.append(row.id)
        return trust(row, envelope)

    assert effective_history(rows, verify_manual=verify) == [third]
    assert verified == [2, 3]
    assert current(rows)["price"] == "11.00"
    assert [vars(row) for row in rows] == originals
    assert [(row.period_start, row.period_end) for row in rows] == [JAN, JAN, JAN]


def test_old_period_correction_does_not_override_latest_price():
    first = observation(1)
    latest = observation(2, "30.00", FEB)
    correction = observation(3, "12.00", supersedes=[first])
    assert current([first, latest, correction])["source_key"] == latest.source_key


def test_unmarked_correction_stays_unmarked_without_clock_date():
    first = observation(1, period=(None, None))
    corrected = observation(2, "11.00", (None, None), supersedes=[first])
    result = current([first, corrected])
    assert result["price"] == "11.00"
    assert result["period_start"] is None
    assert result["period_end"] is None


def test_unmarked_independent_conflict_is_not_last_writer_wins():
    rows = [observation(1, period=(None, None)), observation(2, "11.00", (None, None))]
    with pytest.raises(EltConflict, match="冲突"):
        current(rows)


def test_unselected_independent_same_period_observation_remains_conflicting():
    first, independent = observation(1), observation(2)
    correction = observation(3, "11.00", supersedes=[first])
    assert effective_history([first, independent, correction], verify_manual=trust) == [
        independent,
        correction,
    ]
    with pytest.raises(EltError) as error:
        current([first, independent, correction])
    assert error.value.code == "ELT_PRICE_PERIOD_CONFLICT"


def test_explicitly_reviewed_entire_same_period_group_can_be_corrected():
    first, independent = observation(1), observation(2)
    correction = observation(3, "11.00", supersedes=[first, independent])
    assert current([first, independent, correction])["price"] == "11.00"


def test_independent_overlapping_period_conflict_is_not_suppressed():
    first = observation(1)
    overlap = observation(2, "10.00", (date(2026, 1, 15), date(2026, 2, 15)))
    correction = observation(3, "11.00", supersedes=[first])
    with pytest.raises(EltError) as error:
        current([first, overlap, correction])
    assert error.value.code == "ELT_PRICE_PERIOD_CONFLICT"


@pytest.mark.parametrize("mode", ["missing", "false", "truthy", "old_receipt"])
def test_receipt_validation_is_mandatory_including_superseded_manual_rows(mode):
    first = observation(1)
    second = observation(2, "12.00", supersedes=[first])
    third = observation(3, "11.00", supersedes=[second])
    verifier = {
        "missing": None,
        "false": lambda row, envelope: False,
        "truthy": lambda row, envelope: "true",
        "old_receipt": lambda row, envelope: row.id != 2,
    }[mode]
    with pytest.raises(EltConflict):
        effective_history([first, second, third], verify_manual=verifier)


@pytest.mark.parametrize("kind", ["fork", "self", "forward", "wrong_period", "duplicate"])
def test_correction_must_reference_unique_backward_active_leaves(kind):
    first = observation(1)
    second = observation(2, "12.00", supersedes=[first])
    third = observation(3, "11.00", supersedes=[second])
    if kind == "fork":
        third = observation(3, "11.00", supersedes=[first])
    elif kind == "self":
        third = observation(3, "11.00", supersedes=[third])
    elif kind == "forward":
        second = observation(2, "12.00", supersedes=[third])
    elif kind == "wrong_period":
        third.period_start, third.period_end = FEB
    else:
        third = observation(3, "11.00", supersedes=[second, second])
    with pytest.raises(EltConflict):
        effective_history([first, second, third], verify_manual=trust)


@pytest.mark.parametrize(
    "change",
    [
        {"currency": "USD"},
        {"price_unit": "box"},
        {"actor_id": "8"},
        {"operation_id": "not-a-uuid"},
        {"reason": " "},
        {"kind": "catalog_price_v2"},
        {"receipt_key": "etl_batch_wrong"},
        {"extra": True},
        {"supersedes": "all"},
    ],
)
def test_changed_dimensions_actor_or_unversioned_envelope_fail_closed(change):
    first = observation(1, supersedes=[])
    correction = observation(2, "11.00", supersedes=[first])
    envelope = json.loads(correction.provenance_json)
    envelope.update(change)
    correction.provenance_json = json.dumps(envelope)
    with pytest.raises(EltConflict):
        effective_history([first, correction], verify_manual=trust)


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": 6},
        {"product_id": 12},
        {"id": 1},
        {"source_key": "1"},
        {"period_end": None},
        {"period_end": date(2025, 1, 1)},
    ],
)
def test_history_scope_identity_and_order_are_not_implicitly_repaired(change):
    first, second = observation(1), observation(2, "20.00", FEB)
    for key, value in change.items():
        setattr(second, key, value)
    with pytest.raises(EltConflict):
        effective_history([first, second], verify_manual=trust)


def test_duplicate_source_identity_is_rejected():
    first, second = observation(1), observation(2)
    second.source_key = first.source_key
    with pytest.raises(EltConflict):
        effective_history([first, second], verify_manual=trust)


def test_manual_envelope_cannot_hide_in_legacy_provenance_list():
    row = observation(1, supersedes=[])
    row.provenance_json = json.dumps([json.loads(row.provenance_json)])
    with pytest.raises(EltConflict):
        manual_provenance(row)


@pytest.mark.parametrize(
    "keys,period",
    [
        ([], JAN),
        (["missing"], JAN),
        (["x", "x"], JAN),
        ([f"{1:064x}"], FEB),
        ([f"{1:064x}"], (None, None)),
    ],
)
def test_proposal_selection_cannot_invent_originals_or_period(keys, period):
    with pytest.raises(EltConflict):
        validate_correction([observation(1)], keys, *period)


def test_pure_empty_and_legacy_inputs():
    assert effective_history([], verify_manual=None) == []
    first = observation(1)
    assert effective_history([first], verify_manual=None) == [first]
    with pytest.raises(EltConflict):
        effective_price([])
