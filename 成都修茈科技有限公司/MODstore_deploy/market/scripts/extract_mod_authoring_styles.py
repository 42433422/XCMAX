import pathlib
import re

src = pathlib.Path(__file__).resolve().parents[1] / "src/views/ModAuthoringView.vue"
text = src.read_text(encoding="utf-8")
m = re.search(r"<style scoped>(.*?)</style>", text, re.S)
css = m.group(1).strip() if m else ""
out = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src/features/mod-authoring/shared/mod-authoring.css"
)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(css + "\n", encoding="utf-8")
print("written", out, "bytes", len(css))
