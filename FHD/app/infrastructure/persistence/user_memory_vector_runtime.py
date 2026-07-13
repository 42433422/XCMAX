"""Runtime path resolution for the user-memory vector store."""

from __future__ import annotations

import os

from app.utils.path_utils import get_app_data_dir


def default_user_memory_vector_db_path() -> str:
    env_path = os.environ.get("USER_MEMORY_VECTOR_DB_PATH", "").strip()
    if env_path:
        folder = os.path.dirname(env_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        return env_path
    folder = os.path.join(get_app_data_dir(), "vectors")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "user_memory_vectors.db")
