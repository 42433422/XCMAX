import pathlib
import re

src = pathlib.Path(__file__).resolve().parents[1] / "src/views/ModAuthoringView.vue"
text = src.read_text(encoding="utf-8")
lines = text.splitlines()
# file lines 42-325 inclusive
chunk = "\n".join(lines[41:325])
chunk = re.sub(r'^\s*<section v-show="tab === \'guide\'" class="panel">\s*\n', '<section class="panel">\n', chunk)
chunk = re.sub(r"\n\s*</section>\s*$", "", chunk)
chunk = chunk.replace(
    '<template v-if="suggestedSkills.length || suggestedPricing">',
    '<div v-if="suggestedSkills.length || suggestedPricing">',
)
chunk = chunk.replace(
    "          </div>\n        </template>\n\n        <h3 class=\"sub-title\">工作流",
    "          </div>\n        </div>\n\n        <h3 class=\"sub-title\">工作流",
)
# copy-trim: wrap AI blueprint in details
chunk = chunk.replace(
    '        <div v-if="aiBlueprint" class="ai-blueprint-panel">',
    '        <details v-if="aiBlueprint" class="dev-details ai-report-details">\n'
    '          <summary class="dev-details-summary">AI 制作报告</summary>\n'
    '        <div class="ai-blueprint-panel">',
)
chunk = chunk.replace(
    "        </div>\n\n        <div v-if=\"employeeReadiness\"",
    "        </div>\n        </details>\n\n        <div v-if=\"employeeReadiness\"",
)
# shorten readiness sub
chunk = re.sub(
    r"<p class=\"muted small readiness-sub\">.*?</p>\s*\n\s*</div>\s*\n\s*<div class=\"readiness-head-aside\">",
    '<p class="muted small readiness-sub">点一键闭环：登记员工包并对齐画布。</p>\n            </div>\n            <div class="readiness-head-aside">',
    chunk,
    count=1,
    flags=re.S,
)
# industry panel -> use short hint (IndustryPresetField will be used in wizard; expert keeps inline but shorter)
chunk = re.sub(
    r"<h3 class=\"sub-title\">行业适配</h3>\s*<p class=\"muted small\">.*?</p>",
    '<h3 class="sub-title">行业适配</h3>\n          <p class="muted small">选择行业模板，影响菜单和欢迎语。</p>',
    chunk,
    count=1,
    flags=re.S,
)

script = '''<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'
import IndustryPresetField from '../shared/IndustryPresetField.vue'
import EmployeeReadinessBar from '../shared/EmployeeReadinessBar.vue'
import EmployeeTable from '../shared/EmployeeTable.vue'
import ModChecklist from '../shared/ModChecklist.vue'

const ctx = useModAuthoringContext()
const { modData, modDescriptionLine, tab, scaffoldEnvHint } = ctx
</script>

<template>
'''
footer = "\n</template>\n"

out = pathlib.Path(__file__).resolve().parents[1] / "src/features/mod-authoring/expert/ExpertTabGuide.vue"
# Replace industry block, readiness, employee table, checklist with components
chunk = re.sub(
    r"        <div class=\"industry-adapt-panel\">.*?</div>\n\n        <details",
    "        <IndustryPresetField />\n\n        <details",
    chunk,
    count=1,
    flags=re.S,
)
chunk = re.sub(
    r"        <div v-if=\"employeeReadiness\" class=\"readiness-panel\">.*?</div>\n\n        <!-- AI 流水线",
    "        <EmployeeReadinessBar mode=\"expert\" />\n\n        <!-- AI 流水线",
    chunk,
    count=1,
    flags=re.S,
)
chunk = re.sub(
    r"        <h3 class=\"sub-title\">工作流里会用到的.*?</div>\n\n        <details class=\"dev-details\">",
    "        <EmployeeTable mode=\"expert\" />\n\n        <details class=\"dev-details\">",
    chunk,
    count=1,
    flags=re.S,
)
chunk = re.sub(
    r"        <h3 class=\"sub-title\">本包结构检查</h3>\s*<ul class=\"checklist\">.*?</ul>\n\n        <div v-if=\"artifactNote\"",
    "        <ModChecklist />\n\n        <div v-if=\"artifactNote\"",
    chunk,
    count=1,
    flags=re.S,
)

out.write_text(script + chunk + footer, encoding="utf-8")
print("fixed ExpertTabGuide", len(chunk), "chars")
