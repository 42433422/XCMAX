"""向后兼容 shim：端口定义已下沉至 ``app.domain.ports.embedder``。

DDD 端口归 domain 层所有；application/infrastructure 的历史 import 路径保持不变。
"""

from app.domain.ports.embedder import EmbedderPort

__all__ = ["EmbedderPort"]
