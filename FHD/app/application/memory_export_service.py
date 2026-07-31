"""Markdown 导出服务 MemoryExportService.

把 MemoryNode + 反向引用（backlinks）导出为纯 Markdown 字符串，便于人工审阅、
版本归档与离线分享。导出格式参考 spec 第 5.3 节：

```markdown
## Constraints (N)
### [active] 节点标题
- **node_id**: xxx
- **weight**: 0.92
- **content**: ...
- **backlinks**: [[其他节点]] (relates_to)
```

仅用字符串拼接，不引入 markdown 第三方库。
"""

from __future__ import annotations

from collections import defaultdict

from app.db.models.memory_graph import MemoryNode, MemoryNodeType
from app.infrastructure.memory_graph_store import MemoryGraphStore


def _enum_value(value: object) -> str:
    """安全取出枚举值，兼容 Enum 与原生字符串。"""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


class MemoryExportService:
    """记忆图谱 Markdown 导出器。"""

    def __init__(self, store: MemoryGraphStore) -> None:
        self._store = store

    def export_node(self, node_id: str) -> str:
        """导出单个节点为 Markdown（含元数据 + backlinks）。"""
        node = self._store.get_node(node_id)
        if node is None:
            return f"<!-- node {node_id} not found -->\n"

        lines: list[str] = []
        status_str = _enum_value(node.status)
        lines.append(f"### [{status_str}] {node.title}")
        lines.append(f"- **node_id**: {node.node_id}")
        lines.append(f"- **type**: {_enum_value(node.type)}")
        lines.append(f"- **status**: {status_str}")
        lines.append(f"- **scope**: {node.scope}/{node.scope_id}")
        lines.append(f"- **weight**: {node.metadata_weight:.4f}")
        lines.append(f"- **recall_count**: {node.metadata_recall_count}")
        lines.append(f"- **confidence**: {node.metadata_confidence:.4f}")
        tags = node.tags_list()
        lines.append(f"- **tags**: {', '.join(tags) if tags else ''}")
        lines.append(f"- **content**: {node.content or ''}")

        backlinks = self._store.list_backlinks(node.node_id)
        if backlinks:
            entries: list[str] = []
            for edge in backlinks:
                source = self._store.get_node(edge.source_node_id)
                source_title = source.title if source else "<unknown>"
                arrow = "<->" if edge.bidirectional else "->"
                entries.append(f"  - [[{source_title}]] {arrow} ({_enum_value(edge.type)})")
            lines.append("- **backlinks**:")
            lines.extend(entries)
        else:
            lines.append("- **backlinks**: ")

        return "\n".join(lines) + "\n"

    def export_scope(
        self,
        scope: str,
        scope_id: str,
        node_type: MemoryNodeType | None = None,
    ) -> str:
        """按 scope 导出所有 active 节点，按 type 分组。

        Args:
            scope: 记忆作用域（如 ``project`` / ``user`` / ``tenant``）。
            scope_id: 作用域内的标识（如 ``XCMAX`` / user_id）。
            node_type: 可选过滤；为 None 时导出全部类型。
        """
        if node_type is not None:
            nodes = self._store.list_active_nodes(
                scope=scope, scope_id=scope_id, node_type=node_type
            )
            groups: dict[MemoryNodeType, list[MemoryNode]] = {node_type: nodes}
        else:
            all_nodes = self._store.list_active_nodes(scope=scope, scope_id=scope_id)
            groups = defaultdict(list)
            for n in all_nodes:
                groups[n.type].append(n)

        if not groups or all(len(v) == 0 for v in groups.values()):
            return f"<!-- scope {scope}/{scope_id} has no active memory nodes -->\n"

        # 按 MemoryNodeType 定义顺序稳定排序
        type_order = list(MemoryNodeType)
        sorted_types = sorted(
            groups.keys(), key=lambda t: type_order.index(t) if t in type_order else len(type_order)
        )

        lines: list[str] = []
        for t in sorted_types:
            group_nodes = groups[t]
            if not group_nodes:
                continue
            type_key = _enum_value(t)
            lines.append(f"## {type_key} ({len(group_nodes)})")
            # 按 title 稳定排序，便于 diff
            group_nodes = sorted(group_nodes, key=lambda n: n.title)
            for n in group_nodes:
                lines.append(self.export_node(n.node_id).rstrip())
                lines.append("")  # 节点间空行分隔
            lines.append("")  # 组间空行

        return "\n".join(lines).rstrip() + "\n"
