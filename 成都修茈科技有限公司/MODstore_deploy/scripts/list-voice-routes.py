#!/usr/bin/env python3
from modstore_server.app import app

paths = sorted(
    {
        getattr(r, "path", None)
        for r in app.routes
        if getattr(r, "path", None) and ("voice" in r.path or "asr" in r.path)
    }
)
print(paths)
