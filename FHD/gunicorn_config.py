"""Gunicorn 配置文件

用于生产环境部署，支持高并发。
"""

import multiprocessing
import os

bind = "0.0.0.0:5000"

_default_workers = max(2, multiprocessing.cpu_count() * 2 + 1)
workers = int(os.environ.get("XCAGI_GUNICORN_WORKERS", str(_default_workers)))

# FastAPI ASGI — SSOT；勿在 Dockerfile/compose 再用 CLI -k 覆盖
worker_class = "uvicorn.workers.UvicornWorker"

max_requests = 1000
max_requests_jitter = 50

timeout = 120

keepalive = 5

preload_app = True

daemon = False

pidfile = None

accesslog = "-"

errorlog = "-"

loglevel = "info"

def on_starting(server):
    """服务器启动时的回调"""
    server.log.info("Gunicorn 服务器正在启动...")


def on_reload(server):
    """服务器重载时的回调"""
    server.log.info("Gunicorn 服务器正在重载...")


def when_ready(server):
    """服务器就绪时的回调"""
    server.log.info(f"Gunicorn 服务器已就绪，监听 {bind}")
    server.log.info(f"Worker 数量: {server.app.cfg.workers}")


def on_exit(server):
    """服务器退出时的回调"""
    server.log.info("Gunicorn 服务器正在关闭...")
