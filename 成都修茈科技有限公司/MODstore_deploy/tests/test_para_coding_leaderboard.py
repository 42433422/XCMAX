import json

from modstore_server import para_coding_leaderboard as leaderboard


def test_reads_newest_release_and_exact_coding_ids(monkeypatch):
    requests = []
    assets = {
        "": '<script defer src="./static/js/main.88888888.js"></script>',
        "static/js/main.88888888.js": 'const release=["20261014","20261106"],future=["20261106","20990101"]',
        "data/20261106/table.csv": "model,coding,reasoning\nmodel-v2,75.5,17\nmodel-v1,,90\n",
    }

    def download(_client, path):
        requests.append(path)
        return assets[path]

    monkeypatch.setattr(leaderboard, "_text", download)
    assert leaderboard._fetch_release(-1) == ("20261106", {"model-v2": 75.5})
    assert leaderboard._fetch_release(-1) == ("20261106", {"model-v2": 75.5})
    assert requests == list(assets)
    leaderboard._fetch_release.cache_clear()


def test_invalid_schema_does_not_become_a_ranking(monkeypatch):
    monkeypatch.setattr(leaderboard, "_text", lambda *_: "unrecognized release")
    assert leaderboard._fetch_release(-1) is None
    leaderboard._fetch_release.cache_clear()


def test_deepswe_compares_only_full_runs_from_fixed_harness(monkeypatch):
    selected = {
        "harness": "mini-swe-agent",
        "source": "deep-swe",
        "n_tasks_attempted": 113,
        "config": "test-a",
        "pass_at_1": 0.35,
    }
    data = {
        "n_tasks_in_set": 113,
        "generated_at": "2026-09-22T06:27:15+00:00",
        "rows": [
            selected,
            {**selected, "config": "incomplete", "n_tasks_attempted": 26},
            {**selected, "config": "other-harness", "harness": "other-agent"},
            {**selected, "config": "vendor-report", "source": "third-party"},
        ],
    }
    monkeypatch.setattr(leaderboard, "_asset", lambda *_: json.dumps(data))
    assert leaderboard._fetch_deepswe(-2) == ("2026-09-22T06:27:15+00:00", {"test-a": 35.0})
    leaderboard._fetch_deepswe.cache_clear()
