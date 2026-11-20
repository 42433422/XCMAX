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
