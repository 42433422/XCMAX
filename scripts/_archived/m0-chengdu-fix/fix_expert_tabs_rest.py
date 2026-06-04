import pathlib
import re

src = pathlib.Path(__file__).resolve().parents[1] / "src/views/ModAuthoringView.vue"
# Use backup from git - the view is now thin; read original from first 600 lines in old file?
# Read current ModAuthoringView - it's thin now. Use expert tab broken files + grep original from git
view = pathlib.Path(__file__).resolve().parents[1] / "src/views/ModAuthoringView.vue"
if view.read_text(encoding="utf-8").count("ModAuthoringPage") > 0:
    # recover from expert/ExpertTabGuide partial + manifest in repo history - use fix_expert_tabs by reading backup file
    backup = pathlib.Path(__file__).resolve().parents[1] / "src/views/ModAuthoringView.vue.bak"
    if not backup.exists():
        # extract from git
        import subprocess
        r = subprocess.run(
            ["git", "show", "HEAD:market/src/views/ModAuthoringView.vue"],
            cwd=pathlib.Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if r.returncode == 0:
            lines = r.stdout.splitlines()
        else:
            raise SystemExit("no backup and git failed")
    else:
        lines = backup.read_text(encoding="utf-8").splitlines()
else:
    lines = view.read_text(encoding="utf-8").splitlines()

out_dir = pathlib.Path(__file__).resolve().parents[1] / "src/features/mod-authoring/expert"

tabs = {
    "ExpertTabManifest": (328, 340, """  manifestText,
  manifestSaveWarnings,
  savingManifest,
  saveManifest,
  loading,
  reload,"""),
    "ExpertTabFrontend": (342, 377, """  frontendConfigPath,
  frontendEntryPath,
  frontendSpecTitle,
  frontendSpecPreview,
  frontendBrief,
  frontendBusy,
  regenerateFrontend,
  fileSet,"""),
    "ExpertTabFiles": (378, 403, """  sortedFiles,
  selectedPath,
  fileContent,
  loadingFile,
  savingFile,
  fileWarnings,
  scaffoldEnvHint,
  onPathSelect,
  loadSelectedFile,
  saveFile,"""),
    "ExpertTabSnapshots": (404, 441, """  snapshotsRows,
  snapshotsLoadErr,
  snapshotBusy,
  snapshotLabelDraft,
  formatSnapTime,
  refreshSnapshots,
  captureSnapshotManual,
  restoreSnapshot,
  bumpManifestPatch,"""),
    "ExpertTabScan": (442, 477, """  loadingSummary,
  refreshSummary,
  summary,"""),
}

wrapper_head = """<script setup lang="ts">
import {{ useModAuthoringContext }} from '../composables/useModAuthoringContext'

const ctx = useModAuthoringContext()
const {{
{bindings}
}} = ctx
</script>

<template>
<section class="panel">
"""

wrapper_tail = "\n</section>\n</template>\n"

for name, (start, end, bindings) in tabs.items():
    chunk = "\n".join(lines[start : end])  # end exclusive (line end is end, file line end+1)
    chunk = re.sub(r'^\s*<section v-show="tab === \'[^\']+\'" class="panel">\s*\n', "", chunk)
    chunk = re.sub(r"\n\s*</section>\s*$", "", chunk)
    content = wrapper_head.format(bindings=bindings) + chunk.strip() + wrapper_tail
    (out_dir / f"{name}.vue").write_text(content, encoding="utf-8")
    print("wrote", name)
