import os

import pytest

from app.contexts.flags import is_event_primary_enabled


def test_event_primary_flag_shipment():
    os.environ.pop("XCAGI_EVENT_PRIMARY", None)
    os.environ.pop("XCAGI_EVENT_PRIMARY_SHIPMENT", None)
    assert is_event_primary_enabled("shipment") is False
    os.environ["XCAGI_EVENT_PRIMARY_SHIPMENT"] = "1"
    try:
        assert is_event_primary_enabled("shipment") is True
    finally:
        os.environ.pop("XCAGI_EVENT_PRIMARY_SHIPMENT", None)


def test_event_primary_global():
    os.environ["XCAGI_EVENT_PRIMARY"] = "1"
    try:
        assert is_event_primary_enabled("shipment") is True
    finally:
        os.environ.pop("XCAGI_EVENT_PRIMARY", None)
