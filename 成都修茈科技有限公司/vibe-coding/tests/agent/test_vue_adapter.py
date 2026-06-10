"""Tests for the regex-based Vue Single-File Component adapter."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from vibe_coding.agent.repo_index import VueLanguageAdapter, build_index


@pytest.fixture
def adapter() -> VueLanguageAdapter:
    return VueLanguageAdapter()


def test_extensions(adapter: VueLanguageAdapter) -> None:
    assert ".vue" in adapter.extensions
    assert adapter.language == "vue"
    assert adapter.is_available()


def test_script_setup_extracts_symbols(adapter: VueLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        <script setup lang="ts">
        import { ref } from "vue";

        const count = ref(0);

        function increment() {
          count.value += 1;
        }

        defineProps<{
          label: string;
        }>();
        </script>

        <template>
          <button @click="increment">{{ label }}: {{ count }}</button>
        </template>
        """
    )
    pf = adapter.parse(path="MyButton.vue", source=src)
    names = {s.name for s in pf.symbols}
    # Function declarations are detected; bare ``const`` bindings aren't
    # (those would emit too much noise in production code).
    assert "increment" in names
    assert "vue" in pf.imports
    refs = {r.name for r in pf.references}
    # ``ref(`` is a call reference; ``defineProps<...>()`` is a Vue macro
    # picked up by the adapter's _USE_CALL_RE.
    assert "ref" in refs
    assert "defineProps" in refs


def test_classic_options_api(adapter: VueLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        <script>
        export default {
          name: 'MyComponent',
          props: ['label'],
          methods: {
            doIt() { return 1; }
          }
        };
        </script>

        <template>
          <div>hi</div>
        </template>
        """
    )
    pf = adapter.parse(path="X.vue", source=src)
    # No top-level functions but the parser shouldn't crash.
    assert isinstance(pf.symbols, list)
    assert pf.parse_error == ""


def test_template_extracts_pascalcase_components(adapter: VueLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        <template>
          <div>
            <FooBar :prop="x" />
            <BazQux>nested</BazQux>
            <span>html element, ignored</span>
            <H1>uppercase, no lowercase second char, ignored</H1>
          </div>
        </template>
        """
    )
    pf = adapter.parse(path="Page.vue", source=src)
    component_names = {s.name for s in pf.symbols if s.kind == "component_use"}
    assert "FooBar" in component_names
    assert "BazQux" in component_names
    assert "H1" not in component_names


def test_imports_carried_from_script(adapter: VueLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        <script setup>
        import Foo from './Foo.vue';
        import { useStore } from 'pinia';

        const store = useStore();
        </script>
        """
    )
    pf = adapter.parse(path="X.vue", source=src)
    assert "./Foo.vue" in pf.imports
    assert "pinia" in pf.imports
    refs = {r.name for r in pf.references}
    assert "useStore" in refs


def test_line_offsets_point_into_vue_file(adapter: VueLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        <template><div /></template>

        <script setup lang="ts">
        function helperFn() { return 42; }
        </script>
        """
    )
    pf = adapter.parse(path="X.vue", source=src)
    helper = next(s for s in pf.symbols if s.name == "helperFn")
    # Line should be inside the script block (≥ line 4 in the .vue file).
    assert helper.start_line >= 4


def test_empty_file_returns_empty_parsed(adapter: VueLanguageAdapter) -> None:
    pf = adapter.parse(path="x.vue", source="")
    assert pf.symbols == []
    assert pf.imports == []
    assert pf.references == []


def test_repo_index_indexes_vue_files(tmp_path: Path) -> None:
    (tmp_path / "components").mkdir()
    (tmp_path / "components" / "Hello.vue").write_text(
        "<script setup>\nimport { ref } from 'vue';\nconst x = ref(0);\n</script>\n"
        "<template><div>hi</div></template>\n",
        encoding="utf-8",
    )
    index = build_index(tmp_path)
    assert "vue" in index.summary()["languages"]
    entry = index.get_file("components/Hello.vue")
    assert entry is not None
    assert "vue" in entry.imports


# ---------------------------------------------------------- new (P2 deepening)


def test_define_props_type_literal(adapter: VueLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        <script setup lang="ts">
        defineProps<{
          label: string;
          count?: number;
        }>();
        </script>
        """
    )
    pf = adapter.parse(path="X.vue", source=src)
    props = {s.name for s in pf.symbols if s.kind == "prop"}
    assert {"label", "count"} <= props


def test_define_props_runtime_array(adapter: VueLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        <script setup>
        defineProps(['title', 'description']);
        </script>
        """
    )
    pf = adapter.parse(path="X.vue", source=src)
    props = {s.name for s in pf.symbols if s.kind == "prop"}
    assert {"title", "description"} <= props


def test_define_props_runtime_object(adapter: VueLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        <script setup>
        defineProps({
          msg: String,
          settings: { type: Object, default: () => ({}) },
        });
        </script>
        """
    )
    pf = adapter.parse(path="X.vue", source=src)
    props = {s.name for s in pf.symbols if s.kind == "prop"}
    assert {"msg", "settings"} <= props


def test_define_emits_runtime_array(adapter: VueLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        <script setup>
        defineEmits(['submit', 'cancel']);
        </script>
        """
    )
    pf = adapter.parse(path="X.vue", source=src)
    emits = {s.name for s in pf.symbols if s.kind == "emit"}
    assert {"submit", "cancel"} <= emits


def test_define_emits_type_form(adapter: VueLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        <script setup lang="ts">
        defineEmits<{
          (e: 'submit', value: string): void;
          (e: 'reset'): void;
        }>();
        </script>
        """
    )
    pf = adapter.parse(path="X.vue", source=src)
    emits = {s.name for s in pf.symbols if s.kind == "emit"}
    assert {"submit", "reset"} <= emits


def test_template_slot_named(adapter: VueLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        <template>
          <div>
            <slot name="header" />
            <slot />
            <slot name="footer">default footer</slot>
          </div>
        </template>
        """
    )
    pf = adapter.parse(path="X.vue", source=src)
    slots = {s.name for s in pf.symbols if s.kind == "slot"}
    assert {"header", "footer", "default"} <= slots


def test_template_event_handler_reference(adapter: VueLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        <template>
          <button @click="onLogin">Login</button>
          <button v-on:click="onCancel">Cancel</button>
          <input @input.lazy="onChange" />
          <span @click="count++">inline (skipped)</span>
        </template>
        """
    )
    pf = adapter.parse(path="X.vue", source=src)
    refs = {r.name for r in pf.references}
    assert {"onLogin", "onCancel", "onChange"} <= refs
    # ``count++`` starts with an identifier ``count`` which is OK to surface
    # but should not crash; just ensure no junk like ``++`` ends up in refs.
    assert all("+" not in name for name in refs)
