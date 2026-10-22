from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text()
    if s.count(old) != 1:
        raise RuntimeError(f'Expected exactly one patch anchor in {path}: {old[:80]!r}')
    p.write_text(s.replace(old, new), encoding='utf-8')


aggregate = 'FHD/scripts/ci/backend_shard_aggregate.py'
replace_once(aggregate,
    'from scripts.ci.backend_shards import configured_total, identity, verify',
    'from scripts.ci.backend_shards import configured_total, digest, identity, verify')
replace_once(aggregate, '\n\ndef aggregate(\n', '''

def identical_measurements(root: Path, total: int, prefix: str, summaries: list[dict]) -> bool:
    """Reuse only after both same-run manifests have passed full verification."""
    scopes = [{key: value for key, value in summary.items() if key != "mode"}
              for summary in summaries]
    return len(scopes) == 2 and scopes[0] == scopes[1] and all(
        digest(root / f"{prefix}{index}" / ".coverage.full")
        == digest(root / f"{prefix}{index}" / ".coverage.behavior")
        for index in range(1, total + 1)
    )


def aggregate(
''')
replace_once(aggregate,
    '        with tempfile.TemporaryDirectory(prefix="backend-coverage-") as workspace:\n',
    '''        reuse_behavior = identical_measurements(root, total, artifact_prefix, summaries)
        report["behavior_report_reused"] = reuse_behavior
        with tempfile.TemporaryDirectory(prefix="backend-coverage-") as workspace:
''')
replace_once(aggregate,
    '            for mode in ("full", "behavior"):\n                # Report commands',
    '''            for mode in ("full", "behavior"):
                if mode == "behavior" and reuse_behavior:
                    stage("reuse-json-behavior", lambda: shutil.copyfile(
                        "coverage.json", "coverage-behavior.json"
                    ))
                    continue
                # Report commands''')
plugin = 'FHD/scripts/ci/backend_shard_plugin.py'
replace_once(plugin,
    '        self.started = time.monotonic()\n',
    '''        self.started = time.monotonic()
        self.phase_seconds: dict[str, float] = {}

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_collection(self, session):
        started = time.monotonic()
        try:
            yield
        finally:
            self.phase_seconds["collection"] = time.monotonic() - started

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtestloop(self, session):
        started = time.monotonic()
        try:
            yield
        finally:
            self.phase_seconds["execution"] = time.monotonic() - started
''')
replace_once(plugin, '            elapsed=time.monotonic() - self.started,',
    '            elapsed=time.monotonic() - self.started,\n            phase_seconds=self.phase_seconds,')
p = Path('FHD/tests/test_ci/test_backend_shard_aggregate.py')
p.write_text(p.read_text() + '''

@pytest.fixture
def identical_shards(measured_shards, tmp_path):
    source, env = measured_shards
    root = tmp_path / "identical"
    shutil.copytree(source, root)
    shutil.copyfile(root / "serial-full.json", root / "serial-behavior.json")
    for directory in (root / "shards").iterdir():
        data = json.loads((directory / "full.json").read_text())
        data["mode"] = "behavior"
        (directory / "behavior.json").write_text(json.dumps(data))
        for name in (".coverage", "xml"):
            src, dst = ((".coverage.full", ".coverage.behavior") if name == ".coverage"
                        else ("full.xml", "behavior.xml"))
            shutil.copyfile(directory / src, directory / dst)
        seal(directory)
    return root, env


@pytest.mark.parametrize("failed_gate", ["", "full", "behavior"])
def test_identical_reports_reuse_computation_but_never_skip_gates(identical_shards, failed_gate):
    root, _ = identical_shards
    result = aggregate_run(identical_shards, FAIL_GATE=failed_gate)
    assert result.returncode == (23 if failed_gate else 0), result.stdout + result.stderr
    assert (root / "coverage.json").read_bytes() == (root / "coverage-behavior.json").read_bytes()
    timing = json.loads((root / "backend-aggregate-timings.json").read_text())
    names = [stage["name"] for stage in timing["stages"]]
    assert timing["behavior_report_reused"] is True
    assert names[:2] == ["verify-full", "verify-behavior"]
    assert "reuse-json-behavior" in names
    assert not {"combine-behavior", "json-behavior"}.intersection(names)
    assert names[-1] == ("ratchet-full" if failed_gate == "full" else "ratchet-behavior")
    assert timing["status"] == ("failure" if failed_gate else "success")


@pytest.mark.parametrize("field", ["collected", "outcomes", "collection_skips",
                                  "report_toolchain", "collection_sha256", "outcomes_sha256"])
def test_equal_coverage_bytes_do_not_override_different_scopes(identical_shards, field):
    from scripts.ci.backend_shard_aggregate import identical_measurements
    from scripts.ci.backend_shards import verify

    root, _ = identical_shards
    shards = root / "shards"
    summaries = [verify(shards, 2, mode, IDENTITY, "backend-shard-1-")
                 for mode in ("full", "behavior")]
    assert identical_measurements(shards, 2, "backend-shard-1-", summaries)
    summaries[1][field] = "different"
    assert not identical_measurements(shards, 2, "backend-shard-1-", summaries)


def test_equal_scopes_require_equal_raw_coverage_on_every_shard(identical_shards):
    from scripts.ci.backend_shard_aggregate import identical_measurements
    from scripts.ci.backend_shards import verify

    root, _ = identical_shards
    shards = root / "shards"
    summaries = [verify(shards, 2, mode, IDENTITY, "backend-shard-1-")
                 for mode in ("full", "behavior")]
    target = shards / "backend-shard-1-2/.coverage.behavior"
    original = target.read_bytes()
    target.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    assert not identical_measurements(shards, 2, "backend-shard-1-", summaries)
    result = aggregate_run(identical_shards)
    assert result.returncode != 0
    timing = json.loads((root / "backend-aggregate-timings.json").read_text())
    assert timing["status"] == "failure"
    assert "behavior_report_reused" not in timing


def test_phase_timings_cover_real_collection_and_execution(measured_shards):
    root, _ = measured_shards
    for path in (root / "shards").glob("*/full.json"):
        data = json.loads(path.read_text())
        phases = data["phase_seconds"]
        assert set(phases) == {"collection", "execution"}
        assert all(value >= 0 for value in phases.values())
        assert sum(phases.values()) <= data["elapsed"]
''', encoding='utf-8')
p = Path('FHD/CHANGELOG.md')
s = p.read_text()
lines=s.splitlines(keepends=True)
lines.insert(2, '\n- CI: reuse behavior coverage reporting only for verified identical same-run scopes and per-shard raw data; keep both ratchets and record collection/execution timings.\n')
p.write_text(''.join(lines), encoding='utf-8')
print('candidate patch applied: aggregation, evidence timing, adversarial tests, changelog')
