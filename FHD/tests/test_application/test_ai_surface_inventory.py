"""Surface inventory must retain dynamic ambiguity and avoid comment/test false positives."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.dev.ai_surface_inventory import api_declarations, is_product_source


def test_api_methods_prefixes_and_dynamic_routes():
    rows = api_declarations(
        """
router: APIRouter = APIRouter(prefix="/api/items")
# @router.get("/not-a-route")
@router.get("")
@router.api_route("/{item_id}", methods=["PATCH", "DELETE"])
def edit(): pass
@other.post(dynamic_path)
async def external(): pass
""",
        "app/example.py",
    )
    assert [row["method"] for row in rows] == ["GET", "PATCH", "DELETE", "POST"]
    assert rows[0]["declared_path"] == ""
    assert rows[0]["local_path"] == "/api/items"
    assert rows[1]["local_path"] == "/api/items/{item_id}"
    assert rows[3]["dynamic"] is True and rows[3]["local_path"] is None
    assert all(row["mount_status"] == "unverified" for row in rows)


def test_reused_router_variable_cannot_invent_a_mount_prefix():
    rows = api_declarations(
        """
def first():
    router = APIRouter(prefix="/one")
    @router.get("/x")
    def endpoint(): pass
def second():
    router = APIRouter(prefix="/two")
    @router.get("/y")
    def endpoint(): pass
""",
        "app/routers.py",
    )
    assert len(rows) == 2
    assert all(row["local_path"] is None and row["dynamic"] for row in rows)


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_api.py",
        "frontend/src/App.test.ts",
        "frontend/.tmp-erp-head/view.vue",
        "app/_archive/route.py",
    ],
)
def test_nonproduct_copies_are_excluded(path):
    assert not is_product_source(path)


def test_latest_named_production_file_is_not_mistaken_for_a_test():
    assert is_product_source("app/latest_template.py")


def test_frontend_parser_retains_real_void_file_input_and_ignores_comments(tmp_path):
    root = Path(__file__).resolve().parents[2]
    if not shutil.which("node") or not (root / "frontend/node_modules/typescript").exists():
        pytest.skip("Requires the frontend Node/compiler dependencies")
    path = tmp_path / "Sample.vue"
    path.write_text("""<template>
<!-- <input type="file" @change="fake"> -->
<input type="file" @change="readFile">
<button @click="save">Save</button>
</template>
<script setup lang="ts">
const routes = [{ path: '/real', component: View }, { path: computedPath, component: Other }]
// { path: '/fake', component: Fake }
</script>""")
    result = json.loads(
        subprocess.check_output(
            ["node", str(root / "scripts/dev/ai_surface_frontend.mjs")],
            input=json.dumps([str(path)]).encode(),
            cwd=root,
        )
    )
    assert not result["errors"]
    assert [row["declared_path"] for row in result["routes"]] == ["/real", "computedPath"]
    assert [row["dynamic"] for row in result["routes"]] == [False, True]
    assert len(result["file_inputs"]) == 1
    assert result["file_inputs"][0]["line"] == 3
    assert [row["event"] for row in result["events"]] == ["change", "click"]
