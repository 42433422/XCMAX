from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4

import requests
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_from_directory,
    stream_with_context,
    url_for,
)
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
ASSETS_DIR = BASE_DIR / "assets"
DATA_FILE = BASE_DIR / "activities.json"
NEWS_FILE = BASE_DIR / "news.json"
ALLOWED_PAGES = {
    "index.html",
    "about.html",
    "services.html",
    "solutions.html",
    "cases.html",
    "case-park.html",
    "case-manufacture.html",
    "case-edu.html",
    "news.html",
    "contact.html",
    "honors.html",
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB


def ensure_upload_dir() -> None:
  UPLOAD_DIR.mkdir(exist_ok=True)


def load_activities() -> list[dict]:
  if not DATA_FILE.exists():
    return []
  try:
    return json.loads(DATA_FILE.read_text("utf-8"))
  except Exception:
    return []


def save_activities(items: list[dict]) -> None:
  DATA_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")


def load_news() -> list[dict]:
  if not NEWS_FILE.exists():
    return []
  try:
    return json.loads(NEWS_FILE.read_text("utf-8"))
  except Exception:
    return []


def save_news(items: list[dict]) -> None:
  NEWS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")


def init_default_activities() -> None:
  """初始化默认的 3 条企业活动和对应示意图。"""
  ensure_upload_dir()
  if DATA_FILE.exists():
    return

  defaults = [
      {
          "id": str(uuid4()),
          "title": "企业数字化解决方案交流会",
          "description": "修茈科技联合多家合作伙伴举办数字化转型交流会，分享项目经验与行业实践。",
          "image": "/uploads/activity_banner_1.svg",
          "date": "2026-03-01",
      },
      {
          "id": str(uuid4()),
          "title": "项目实施现场回访",
          "description": "项目组走进客户现场，持续跟踪系统运行情况，听取一线反馈并优化方案。",
          "image": "/uploads/activity_banner_2.svg",
          "date": "2026-02-18",
      },
      {
          "id": str(uuid4()),
          "title": "年度表彰与团队建设活动",
          "description": "公司举办年度表彰活动，对优秀项目团队和个人进行表彰，并开展团队拓展。",
          "image": "/uploads/activity_banner_3.svg",
          "date": "2026-01-10",
      },
  ]

  # 写入默认数据
  save_activities(defaults)

  # 写入 3 张长条 SVG 示意图
  svg_template = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="260">
  <defs>
    <linearGradient id="grad{n}" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" style="stop-color:{c1};stop-opacity:1" />
      <stop offset="100%" style="stop-color:{c2};stop-opacity:1" />
    </linearGradient>
  </defs>
  <rect width="1200" height="260" fill="url(#grad{n})" rx="20" ry="20"/>
  <text x="60" y="120" font-size="32" fill="#ffffff" font-family="Microsoft YaHei, Arial, sans-serif">
    成都修茈科技有限公司 · 企业活动示意图 {n}
  </text>
  <text x="60" y="168" font-size="18" fill="#eef2ff" font-family="Microsoft YaHei, Arial, sans-serif">
    可在后台上传真实活动图片替换本示意图
  </text>
</svg>
"""
  colors = [
      ("#1d4f91", "#3b82f6"),
      ("#036666", "#22c55e"),
      ("#7c2d12", "#f97316"),
  ]
  for idx, (c1, c2) in enumerate(colors, start=1):
    svg = svg_template.format(n=idx, c1=c1, c2=c2)
    (UPLOAD_DIR / f"activity_banner_{idx}.svg").write_text(svg, "utf-8")


@app.route("/")
def index():
  # 直接返回现有的 index.html
  return send_from_directory(BASE_DIR, "index.html")


@app.route("/<page_name>.html")
def static_page(page_name: str):
  file_name = f"{page_name}.html"
  if file_name not in ALLOWED_PAGES:
    return send_from_directory(BASE_DIR, "index.html")
  return send_from_directory(BASE_DIR, file_name)


@app.route("/styles.css")
def styles():
  return send_from_directory(BASE_DIR, "styles.css")


@app.route("/main.js")
def main_js():
  return send_from_directory(BASE_DIR, "main.js")


@app.route("/assets/<path:filename>")
def assets_static(filename: str):
  return send_from_directory(ASSETS_DIR, filename)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename: str):
  return send_from_directory(UPLOAD_DIR, filename)


@app.route("/api/activities")
def api_activities():
  items = load_activities()
  # 新到旧排序
  items_sorted = sorted(items, key=lambda x: x.get("date", ""), reverse=True)
  return jsonify(items_sorted)


@app.route("/api/news")
def api_news():
  items = load_news()
  items_sorted = sorted(items, key=lambda x: x.get("date", ""), reverse=True)
  return jsonify(items_sorted)


# ---------------------------------------------------------------------------
# ModStore（FastAPI，见 MODstore_deploy/modstore_server）反向代理
# 线上需同时运行 Uvicorn，例如：uvicorn modstore_server.app:app --host 127.0.0.1 --port 8000
# 可通过环境变量 MODSTORE_BACKEND_URL 覆盖默认后端地址。
# ---------------------------------------------------------------------------
MODSTORE_BACKEND = os.environ.get("MODSTORE_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")

# 浏览器跨域访问 /api/*（反代 ModStore）时由 Flask 补齐 CORS，避免 Nginx/上游未带预检头。
_MODSTORE_CORS_ORIGINS_RAW = os.environ.get("MODSTORE_CORS_ORIGINS", "").strip()
if _MODSTORE_CORS_ORIGINS_RAW:
  _MODSTORE_CORS_ORIGINS = frozenset(
      o.strip() for o in _MODSTORE_CORS_ORIGINS_RAW.split(",") if o.strip()
  )
else:
  _MODSTORE_CORS_ORIGINS = frozenset(
      {
          "https://xiu-ci.com",
          "https://www.xiu-ci.com",
          "http://127.0.0.1:5173",
          "http://localhost:5173",
          "http://127.0.0.1:4173",
          "http://localhost:4173",
      }
  )
_cors_regex_raw = os.environ.get("MODSTORE_CORS_ORIGIN_REGEX", "").strip()
if _cors_regex_raw.lower() in ("0", "false", "none", "-"):
  _MODSTORE_CORS_ORIGIN_RE = None
elif _cors_regex_raw:
  _MODSTORE_CORS_ORIGIN_RE = re.compile(_cors_regex_raw)
else:
  _MODSTORE_CORS_ORIGIN_RE = re.compile(r"^https://[a-zA-Z0-9.-]+\.edgeone\.cool$")


def _reflect_cors_origin(origin: str | None) -> str | None:
  if not origin:
    return None
  if origin in _MODSTORE_CORS_ORIGINS:
    return origin
  if _MODSTORE_CORS_ORIGIN_RE and _MODSTORE_CORS_ORIGIN_RE.match(origin):
    return origin
  return None


def _apply_cors_headers(resp: Response) -> None:
  allowed = _reflect_cors_origin(request.headers.get("Origin"))
  if not allowed:
    return
  resp.headers["Access-Control-Allow-Origin"] = allowed
  resp.headers["Access-Control-Allow-Credentials"] = "true"
  vary = resp.headers.get("Vary")
  if vary:
    parts = [p.strip() for p in vary.split(",") if p.strip()]
    if "Origin" not in parts:
      resp.headers["Vary"] = f"{vary}, Origin"
  else:
    resp.headers["Vary"] = "Origin"


@app.after_request
def _cors_after_all_api_paths(response: Response):
  """凡经 Flask 的 /api/* 响应若尚无 CORS 头则补齐（含 /api/activities、/api/news）。"""
  try:
    path = request.path or ""
  except RuntimeError:
    return response
  if not (path.startswith("/api") or path.startswith("/v1")):
    return response
  if response.headers.get("Access-Control-Allow-Origin"):
    return response
  _apply_cors_headers(response)
  return response


_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-encoding",
    }
)


def _modstore_target_url(subpath: str) -> str:
  base = f"{MODSTORE_BACKEND}/api/{subpath}"
  qs = request.query_string.decode("utf-8")
  return f"{base}?{qs}" if qs else base


def _headers_to_upstream() -> dict[str, str]:
  out: dict[str, str] = {}
  for key, value in request.headers:
    lk = key.lower()
    if lk in _HOP_BY_HOP or lk == "host":
      continue
    out[key] = value
  return out


@app.route(
    "/api/<path:subpath>",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
def proxy_modstore_api(subpath: str):
  reflected = _reflect_cors_origin(request.headers.get("Origin"))

  if request.method == "OPTIONS":
    if not reflected:
      return Response("", status=403)
    req_hdrs = request.headers.get("Access-Control-Request-Headers", "")
    allow_headers = req_hdrs or "authorization, content-type"
    return Response(
        "",
        status=204,
        headers={
            "Access-Control-Allow-Origin": reflected,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD",
            "Access-Control-Allow-Headers": allow_headers,
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
            "Cache-Control": "private, max-age=0, no-store",
        },
    )

  url = _modstore_target_url(subpath)
  method = request.method
  headers = _headers_to_upstream()
  data = None if method in ("GET", "HEAD") else request.get_data()
  try:
    upstream = requests.request(
        method,
        url,
        headers=headers,
        data=data,
        stream=True,
        timeout=120,
        allow_redirects=False,
    )
  except requests.RequestException as exc:
    err = jsonify({"detail": f"ModStore 后端不可用（请检查 Uvicorn 与 MODSTORE_BACKEND_URL）: {exc}"})
    err.status_code = 502
    _apply_cors_headers(err)
    return err

  excluded_resp = _HOP_BY_HOP | {"content-length"}

  def generate():
    for chunk in upstream.iter_content(chunk_size=65536):
      if chunk:
        yield chunk

  resp = Response(stream_with_context(generate()), status=upstream.status_code)
  for key, value in upstream.headers.items():
    lk = key.lower()
    if lk in excluded_resp or lk.startswith("access-control-"):
      continue
    resp.headers[key] = value
  _apply_cors_headers(resp)
  return resp


ADMIN_SHARED_CSS = """
      body {
        margin: 0;
        padding: 0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei",
          "PingFang SC", "Helvetica Neue", Arial, sans-serif;
        background: #f3f4f6;
        color: #111827;
      }
      .wrap {
        max-width: 960px;
        margin: 24px auto;
        padding: 16px 20px 24px;
        border-radius: 10px;
        background: #ffffff;
        box-shadow: 0 10px 30px rgba(15, 23, 42, 0.12);
      }
      h1 {
        margin-top: 0;
        font-size: 22px;
        border-left: 4px solid #1d4f91;
        padding-left: 10px;
      }
      .tip {
        font-size: 13px;
        color: #4b5563;
        margin-bottom: 16px;
      }
      form {
        border-top: 1px solid #e5e7eb;
        padding-top: 16px;
        margin-top: 8px;
      }
      .field {
        margin-bottom: 12px;
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-size: 14px;
      }
      .field input[type="text"],
      .field input[type="date"],
      .field textarea {
        border-radius: 6px;
        border: 1px solid #d1d5db;
        padding: 7px 9px;
        font-size: 14px;
        outline: none;
      }
      .field input:focus,
      .field textarea:focus {
        border-color: #1d4f91;
        box-shadow: 0 0 0 1px rgba(29, 79, 145, 0.5);
      }
      button {
        padding: 8px 18px;
        border-radius: 999px;
        border: none;
        background: #1d4f91;
        color: #ffffff;
        font-size: 14px;
        cursor: pointer;
      }
      button:hover {
        background: #18406f;
      }
      .list {
        margin-top: 18px;
        border-top: 1px solid #e5e7eb;
        padding-top: 10px;
        font-size: 14px;
      }
      .item {
        padding: 6px 0;
        border-bottom: 1px dashed #e5e7eb;
      }
      .item:last-child {
        border-bottom: none;
      }
      .item span {
        color: #6b7280;
        margin-right: 4px;
      }
      .back-link {
        font-size: 13px;
        margin-bottom: 6px;
      }
      .back-link a {
        color: #1d4f91;
        text-decoration: none;
      }
"""

ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <title>企业活动管理 - 成都修茈科技有限公司</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <style>
""" + ADMIN_SHARED_CSS + """
      .field input[type="file"] {
        font-size: 14px;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="back-link">
        <a href="{{ url_for('index') }}" target="_blank">返回门户首页（新窗口打开）</a>
      </div>
      <h1>企业活动管理后台</h1>
      <p class="tip">
        通过本页面上传企业活动图片和文字说明，前台首页“企业活动”模块会自动展示最新内容。图片建议比例为宽屏长条（例如
        1200 × 260 像素）。
      </p>
      <form method="post" enctype="multipart/form-data">
        <div class="field">
          <label for="title">活动标题（必填）</label>
          <input type="text" id="title" name="title" required />
        </div>
        <div class="field">
          <label for="date">活动日期（可选，不填则自动使用当前日期）</label>
          <input type="date" id="date" name="date" />
        </div>
        <div class="field">
          <label for="description">活动描述（必填）</label>
          <textarea id="description" name="description" rows="3" required></textarea>
        </div>
        <div class="field">
          <label for="image">活动图片（必填，支持 jpg / png / svg 等）</label>
          <input type="file" id="image" name="image" accept="image/*" required />
        </div>
        <button type="submit">上传活动</button>
      </form>

      <div class="list">
        <strong>当前已发布活动（按时间排序）：</strong>
        {% if activities %}
          {% for a in activities %}
          <div class="item">
            <div><span>日期：</span>{{ a.date }}</div>
            <div><span>标题：</span>{{ a.title }}</div>
          </div>
          {% endfor %}
        {% else %}
          <p>暂无活动数据。</p>
        {% endif %}
      </div>
    </div>
  </body>
  </html>
"""

NEWS_ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <title>新闻中心管理 - 成都修茈科技有限公司</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <style>
      body {
        margin: 0;
        padding: 0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei",
          "PingFang SC", "Helvetica Neue", Arial, sans-serif;
        background: #f3f4f6;
        color: #111827;
      }
      .wrap {
        max-width: 960px;
        margin: 24px auto;
        padding: 16px 20px 24px;
        border-radius: 10px;
        background: #ffffff;
        box-shadow: 0 10px 30px rgba(15, 23, 42, 0.12);
      }
      h1 {
        margin-top: 0;
        font-size: 22px;
        border-left: 4px solid #1d4f91;
        padding-left: 10px;
      }
      .tip {
        font-size: 13px;
        color: #4b5563;
        margin-bottom: 16px;
      }
      form {
        border-top: 1px solid #e5e7eb;
        padding-top: 16px;
        margin-top: 8px;
      }
      .field {
        margin-bottom: 12px;
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-size: 14px;
      }
      .field input[type="text"],
      .field input[type="date"],
      .field textarea {
        border-radius: 6px;
        border: 1px solid #d1d5db;
        padding: 7px 9px;
        font-size: 14px;
        outline: none;
      }
      .field input:focus,
      .field textarea:focus {
        border-color: #1d4f91;
        box-shadow: 0 0 0 1px rgba(29, 79, 145, 0.5);
      }
      button {
        padding: 8px 18px;
        border-radius: 999px;
        border: none;
        background: #1d4f91;
        color: #ffffff;
        font-size: 14px;
        cursor: pointer;
      }
      button:hover {
        background: #18406f;
      }
      .list {
        margin-top: 18px;
        border-top: 1px solid #e5e7eb;
        padding-top: 10px;
        font-size: 14px;
      }
      .item {
        padding: 6px 0;
        border-bottom: 1px dashed #e5e7eb;
      }
      .item:last-child {
        border-bottom: none;
      }
      .item span {
        color: #6b7280;
        margin-right: 4px;
      }
      .back-link {
        font-size: 13px;
        margin-bottom: 6px;
      }
      .back-link a {
        color: #1d4f91;
        text-decoration: none;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="back-link">
        <a href="{{ url_for('index') }}" target="_blank">返回网站首页（新窗口打开）</a>
      </div>
      <h1>新闻中心管理</h1>
      <p class="tip">
        通过本页面发布公司新闻和通知公告，前台“新闻中心”页面会自动展示最新内容。
      </p>
      <form method="post">
        <div class="field">
          <label for="title">新闻标题（必填）</label>
          <input type="text" id="title" name="title" required />
        </div>
        <div class="field">
          <label for="date">发布日期（可选，不填则自动使用当前日期）</label>
          <input type="date" id="date" name="date" />
        </div>
        <div class="field">
          <label for="category">类别（如：公司新闻 / 通知公告）</label>
          <input type="text" id="category" name="category" />
        </div>
        <div class="field">
          <label for="summary">简要摘要（对外展示的简短说明）</label>
          <textarea id="summary" name="summary" rows="3" required></textarea>
        </div>
        <button type="submit">发布新闻</button>
      </form>

      <div class="list">
        <strong>当前已发布新闻（按时间排序）：</strong>
        {% if news %}
          {% for n in news %}
          <div class="item">
            <div><span>日期：</span>{{ n.date }}</div>
            <div><span>类别：</span>{{ n.category or '公司新闻' }}</div>
            <div><span>标题：</span>{{ n.title }}</div>
          </div>
          {% endfor %}
        {% else %}
          <p>暂无新闻数据。</p>
        {% endif %}
      </div>
    </div>
  </body>
  </html>
"""


@app.route("/admin", methods=["GET", "POST"])
def admin():
  ensure_upload_dir()
  if request.method == "POST":
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    date = request.form.get("date", "").strip()
    file = request.files.get("image")

    if not title or not description or not file:
      return redirect(url_for("admin"))

    secure_name = secure_filename(file.filename or "")
    if not secure_name:
      return redirect(url_for("admin"))

    ext = Path(secure_name).suffix or ".png"
    filename = f"activity_{int(time.time())}_{uuid4().hex[:8]}{ext}"
    save_path = UPLOAD_DIR / filename
    file.save(save_path)

    if not date:
      # 简单用当前日期（YYYY-MM-DD）
      date = time.strftime("%Y-%m-%d", time.localtime())

    items = load_activities()
    items.append(
        {
            "id": str(uuid4()),
            "title": title,
            "description": description,
            "image": f"/uploads/{filename}",
            "date": date,
        }
    )
    save_activities(items)

    return redirect(url_for("admin"))

  activities = load_activities()
  activities_sorted = sorted(activities, key=lambda x: x.get("date", ""), reverse=True)
  return render_template_string(ADMIN_TEMPLATE, activities=activities_sorted)


@app.route("/admin/news", methods=["GET", "POST"])
def admin_news():
  if request.method == "POST":
    title = request.form.get("title", "").strip()
    summary = request.form.get("summary", "").strip()
    category = request.form.get("category", "").strip()
    date = request.form.get("date", "").strip()

    if not title or not summary:
      return redirect(url_for("admin_news"))

    if not date:
      date = time.strftime("%Y-%m-%d", time.localtime())

    items = load_news()
    items.append(
        {
            "id": str(uuid4()),
            "title": title,
            "summary": summary,
            "category": category or "公司新闻",
            "date": date,
        }
    )
    save_news(items)
    return redirect(url_for("admin_news"))

  news_items = load_news()
  news_sorted = sorted(news_items, key=lambda x: x.get("date", ""), reverse=True)
  return render_template_string(NEWS_ADMIN_TEMPLATE, news=news_sorted)


if __name__ == "__main__":
  init_default_activities()
  app.run(host="0.0.0.0", port=9999, debug=True)


