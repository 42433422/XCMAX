from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "xcmax_dr_apply_release.sh"


class FhdRuntimeBootstrapTest(unittest.TestCase):
    def test_bootstraps_vendored_langgraph_before_restart(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        function_start = text.index("bootstrap_fhd_vendored_langgraph()")
        apply_start = text.index("apply_fhd()")
        call = text.index(
            'bootstrap_fhd_vendored_langgraph "$target" "$target/.venv/bin/python"',
            apply_start,
        )
        compile_step = text.index('"$target/.venv/bin/python" -m compileall', call)

        self.assertLess(function_start, apply_start)
        self.assertLess(apply_start, call)
        self.assertLess(call, compile_step)
        function_text = text[function_start:apply_start]
        self.assertIn("requirements-langgraph-runtime.txt", function_text)
        self.assertIn("xcagi_vendored_langgraph.pth", function_text)
        self.assertIn("assert_vendored_sources", function_text)
        self.assertIn('"$service_python" -m pip install', function_text)
        for package in (
            "xcagi_langgraph_core",
            "xcagi_langgraph_checkpoint",
            "xcagi_langgraph_checkpoint_backends/checkpoint-sqlite",
            "xcagi_langgraph_checkpoint_backends/checkpoint-postgres",
            "xcagi_langgraph_prebuilt",
            "xcagi_langgraph_sdk",
        ):
            self.assertIn(package, function_text)


if __name__ == "__main__":
    unittest.main()
