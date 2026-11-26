import time

import pytest

from tests.test_application.test_xiaox_goal_verifier import goal, response, review
from tests.test_application.test_xiaox_goal_verifier import verifier as verifier


@pytest.mark.parametrize(("remaining", "expected"), [(75, 75), (150, 90)])
def test_mimo_review_wait_uses_only_the_remaining_task_and_review_budget(
    verifier, remaining, expected
):
    verifier.config.model = "mimo-v2.6-pro"
    verifier.config.timeout_seconds = 60
    verifier.config.turn_timeout_seconds = 180
    runtime = verifier.run.metadata["xiaox_runtime"]
    runtime.update(
        runtime_config={"upstream_vendor": "xiaomi"}, deadline_at=time.time() + remaining
    )
    verifier.replies = [response(review(goal(), goal("再查询second", goal_id="second")))]

    assert verifier.verify()["accepted"]
    assert verifier.requests[0].extensions["timeout"]["read"] == pytest.approx(expected, abs=1)
