"""Tests for the regex-based TypeScript / TSX language adapter."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from vibe_coding.agent.repo_index import (
    TypeScriptLanguageAdapter,
    build_index,
)


@pytest.fixture
def adapter() -> TypeScriptLanguageAdapter:
    return TypeScriptLanguageAdapter()


def test_extensions(adapter: TypeScriptLanguageAdapter) -> None:
    assert ".ts" in adapter.extensions
    assert ".tsx" in adapter.extensions
    assert ".js" in adapter.extensions


def test_function_declaration(adapter: TypeScriptLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        export function add(a: number, b: number): number {
          return a + b;
        }
        """
    )
    pf = adapter.parse(path="x.ts", source=src)
    fn = next(s for s in pf.symbols if s.name == "add")
    assert fn.kind == "function"
    assert fn.exported is True


def test_async_function(adapter: TypeScriptLanguageAdapter) -> None:
    src = "async function fetchUser(id: string) { return await db.find(id); }\n"
    pf = adapter.parse(path="x.ts", source=src)
    fn = next(s for s in pf.symbols if s.name == "fetchUser")
    assert fn.kind == "async_function"


def test_arrow_function(adapter: TypeScriptLanguageAdapter) -> None:
    src = "const add = (a: number, b: number) => a + b;\n"
    pf = adapter.parse(path="x.ts", source=src)
    fn = next(s for s in pf.symbols if s.name == "add")
    assert fn.kind == "function"


def test_async_arrow_function(adapter: TypeScriptLanguageAdapter) -> None:
    src = "export const fetcher = async (url: string) => fetch(url);\n"
    pf = adapter.parse(path="x.ts", source=src)
    fn = next(s for s in pf.symbols if s.name == "fetcher")
    assert fn.kind == "async_function"
    assert fn.exported is True


def test_class_with_methods(adapter: TypeScriptLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        export class Calculator {
          public add(a: number, b: number): number {
            return a + b;
          }

          private helper(): void {
            console.log("internal");
          }
        }
        """
    )
    pf = adapter.parse(path="calc.ts", source=src)
    cls = next(s for s in pf.symbols if s.name == "Calculator")
    assert cls.kind == "class"
    methods = [s for s in pf.symbols if s.kind == "method" and s.parent == "Calculator"]
    method_names = {m.name for m in methods}
    assert {"add", "helper"} <= method_names


def test_interface(adapter: TypeScriptLanguageAdapter) -> None:
    src = "export interface User {\n  name: string;\n  age: number;\n}\n"
    pf = adapter.parse(path="x.ts", source=src)
    iface = next(s for s in pf.symbols if s.name == "User")
    assert iface.kind == "interface"


def test_type_alias(adapter: TypeScriptLanguageAdapter) -> None:
    src = "export type UserID = string;\n"
    pf = adapter.parse(path="x.ts", source=src)
    alias = next(s for s in pf.symbols if s.name == "UserID")
    assert alias.kind == "type_alias"


def test_enum(adapter: TypeScriptLanguageAdapter) -> None:
    src = "enum Status { Active, Inactive }\n"
    pf = adapter.parse(path="x.ts", source=src)
    e = next(s for s in pf.symbols if s.name == "Status")
    assert e.kind == "enum"


def test_imports_extracted(adapter: TypeScriptLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        import { foo } from "./foo";
        import bar from 'bar';
        import "side-effect";
        const dyn = require('dynamic');
        const lazy = import('./lazy');
        """
    )
    pf = adapter.parse(path="x.ts", source=src)
    assert "./foo" in pf.imports
    assert "bar" in pf.imports
    assert "side-effect" in pf.imports
    assert "dynamic" in pf.imports
    assert "./lazy" in pf.imports


def test_call_references(adapter: TypeScriptLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        function main() {
          doSomething();
          obj.method();
        }
        """
    )
    pf = adapter.parse(path="x.ts", source=src)
    names = {r.name for r in pf.references}
    assert "doSomething" in names
    assert "obj.method" in names


def test_comments_stripped_before_parsing(adapter: TypeScriptLanguageAdapter) -> None:
    """Symbols inside ``//`` and ``/* … */`` comments must not be detected."""
    src = textwrap.dedent(
        """\
        // function fakeOne() {}
        /* function fakeTwo() {} */
        function realOne() { return 1; }
        """
    )
    pf = adapter.parse(path="x.ts", source=src)
    names = {s.name for s in pf.symbols}
    assert "realOne" in names
    assert "fakeOne" not in names
    assert "fakeTwo" not in names


def test_strings_with_keywords_not_parsed_as_symbols(adapter: TypeScriptLanguageAdapter) -> None:
    """A string literal containing the word ``function`` must not produce a symbol."""
    src = 'const message = "function hidden() { not real }";\n'
    pf = adapter.parse(path="x.ts", source=src)
    assert all(s.name != "hidden" for s in pf.symbols)


def test_tolerant_partial_parse(adapter: TypeScriptLanguageAdapter) -> None:
    """A syntactically broken file should still produce some output."""
    src = "function ok() { return 1; }\nfunction broken( {\n"
    pf = adapter.parse(path="x.ts", source=src)
    names = {s.name for s in pf.symbols}
    assert "ok" in names


def test_repo_index_picks_up_typescript(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text(
        "export function foo() { return 1; }\n", encoding="utf-8"
    )
    (tmp_path / "src" / "b.tsx").write_text(
        "import {foo} from './a';\nexport const Component = () => foo();\n",
        encoding="utf-8",
    )
    index = build_index(tmp_path)
    summary = index.summary()
    assert "typescript" in summary["languages"]
    assert summary["languages"]["typescript"] >= 2


# ---------------------------------------------------------- new (P2 deepening)


def test_export_default_function_named(adapter: TypeScriptLanguageAdapter) -> None:
    src = "export default function App() { return null; }\n"
    pf = adapter.parse(path="App.tsx", source=src)
    app = next(s for s in pf.symbols if s.name == "App")
    assert app.kind == "function"
    assert app.exported is True


def test_export_default_class_named(adapter: TypeScriptLanguageAdapter) -> None:
    src = "export default class HomePage { render() {} }\n"
    pf = adapter.parse(path="page.tsx", source=src)
    cls = next(s for s in pf.symbols if s.name == "HomePage")
    assert cls.kind == "class"
    assert cls.exported is True


def test_export_default_anonymous_function_uses_default_name(
    adapter: TypeScriptLanguageAdapter,
) -> None:
    src = "export default function () { return 1; }\n"
    pf = adapter.parse(path="x.ts", source=src)
    assert any(s.name == "default" and s.kind == "function" for s in pf.symbols)


def test_reexport_module_added_to_imports(adapter: TypeScriptLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        export { foo } from './foo';
        export * from './bar';
        export type { Baz } from './baz';
        """
    )
    pf = adapter.parse(path="index.ts", source=src)
    assert "./foo" in pf.imports
    assert "./bar" in pf.imports
    assert "./baz" in pf.imports


def test_decorator_emits_reference(adapter: TypeScriptLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        @Component({ selector: 'app-root' })
        export class AppComponent {
          @Input() name = '';
        }
        """
    )
    pf = adapter.parse(path="app.component.ts", source=src)
    names = {r.name for r in pf.references}
    assert "Component" in names
    assert "Input" in names


def test_decorator_dotted(adapter: TypeScriptLanguageAdapter) -> None:
    src = "@nestjs.Get('/users') findUsers() {}\n"
    pf = adapter.parse(path="x.ts", source=src)
    names = {r.name for r in pf.references}
    assert "nestjs.Get" in names


def test_jsx_component_use_recorded_in_tsx(adapter: TypeScriptLanguageAdapter) -> None:
    src = textwrap.dedent(
        """\
        import { Layout } from './Layout';
        export function App() {
          return <Layout title="home"><Sidebar /><Main.Content /></Layout>;
        }
        """
    )
    pf = adapter.parse(path="App.tsx", source=src)
    component_uses = {s.name for s in pf.symbols if s.kind == "component_use"}
    assert "Layout" in component_uses
    assert "Sidebar" in component_uses
    assert "Main.Content" in component_uses


def test_jsx_html_tags_ignored(adapter: TypeScriptLanguageAdapter) -> None:
    src = "export const X = () => <div><span>hi</span></div>;\n"
    pf = adapter.parse(path="X.tsx", source=src)
    assert all(s.kind != "component_use" for s in pf.symbols)


def test_ts_file_does_not_emit_jsx_components(
    adapter: TypeScriptLanguageAdapter,
) -> None:
    """A ``.ts`` file with ``Foo<Bar>(x)`` is generic syntax, not JSX."""
    src = "function applyGeneric<Bar>(x: Bar): Bar { return x; }\n"
    pf = adapter.parse(path="util.ts", source=src)
    assert all(s.kind != "component_use" for s in pf.symbols)
