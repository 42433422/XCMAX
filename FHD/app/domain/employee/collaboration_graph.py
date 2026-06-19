# -*- coding: utf-8 -*-
"""员工协作依赖图值对象。

把 ``collaboration.depends_on`` 建模为有向图，提供：
- 拓扑排序（上游依赖先于下游，root 排在最后）
- 环检测（避免相互依赖导致死循环）

仅做纯图算法，不触碰任何 I/O；具体加载由应用层 orchestrator 注入 edges。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CollaborationGraph:
    # employee_id -> 它依赖（需先执行）的 employee_id 列表
    edges: dict[str, list[str]] = field(default_factory=dict)

    def add(self, employee_id: str, depends_on: list[str]) -> None:
        eid = str(employee_id or "").strip()
        if not eid:
            return
        deps = [
            str(d).strip() for d in (depends_on or []) if str(d).strip() and str(d).strip() != eid
        ]
        self.edges[eid] = list(dict.fromkeys(deps))

    def detect_cycle(self) -> list[str] | None:
        """返回检测到的一条环路径（含重复起点）；无环返回 None。"""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = dict.fromkeys(self.edges, WHITE)
        path: list[str] = []

        def visit(node: str) -> list[str] | None:
            color[node] = GRAY
            path.append(node)
            for dep in self.edges.get(node, []):
                if dep not in color:
                    color[dep] = WHITE
                if color.get(dep) == GRAY:
                    idx = path.index(dep) if dep in path else 0
                    return path[idx:] + [dep]
                if color.get(dep) == WHITE:
                    found = visit(dep)
                    if found:
                        return found
            color[node] = BLACK
            path.pop()
            return None

        for n in list(self.edges.keys()):
            if color.get(n, WHITE) == WHITE:
                found = visit(n)
                if found:
                    return found
        return None

    def execution_order(self, root: str) -> list[str]:
        """返回执行 root 所需的顺序：依赖在前，root 在最后。

        若存在环，则尽力返回去环后的偏序（避免无限递归）。
        """
        root = str(root or "").strip()
        if not root:
            return []
        order: list[str] = []
        visited: set[str] = set()
        on_stack: set[str] = set()

        def visit(node: str) -> None:
            if node in visited or node in on_stack:
                return
            on_stack.add(node)
            for dep in self.edges.get(node, []):
                visit(dep)
            on_stack.discard(node)
            visited.add(node)
            order.append(node)

        visit(root)
        return order


__all__ = ["CollaborationGraph"]
