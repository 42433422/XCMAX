# syntax=docker/dockerfile:1
# --- builder：gcc / libpq-dev 仅在此阶段；项目装入 /app 并 -e 安装到 /venv ---
FROM python:3.11-slim AS builder

ARG APT_MIRROR=
# 可选：国内构建加速，例如 https://pypi.tuna.tsinghua.edu.cn/simple（与 docker-compose build.args / .env 中 PIP_INDEX_URL 对应）
ARG PIP_INDEX_URL=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN set -ex \
  && if [ -n "$APT_MIRROR" ]; then \
       MIRROR=$(echo "$APT_MIRROR" | sed 's|/$||'); \
       for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do \
         [ -f "$f" ] || continue; \
         sed -i \
           -e "s|http://deb.debian.org/debian-security|${MIRROR}/debian-security|g" \
           -e "s|https://deb.debian.org/debian-security|${MIRROR}/debian-security|g" \
           -e "s|http://deb.debian.org/debian|${MIRROR}/debian|g" \
           -e "s|https://deb.debian.org/debian|${MIRROR}/debian|g" \
           "$f" 2>/dev/null || true; \
       done; \
     fi \
  && apt-get update \
  && apt-get install -y --no-install-recommends gcc libpq-dev \
  && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY pyproject.toml ./
COPY modman ./modman
COPY modstore_server ./modstore_server
COPY scripts ./scripts

RUN pip install --no-cache-dir --upgrade pip \
    && if [ -n "$PIP_INDEX_URL" ]; then \
         pip install --no-cache-dir -i "$PIP_INDEX_URL" -e ".[web,knowledge]"; \
       else \
         pip install --no-cache-dir -e ".[web,knowledge]"; \
       fi

# --- runtime：复制 venv + 源码树；仅 libpq5；无 gcc ---
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends libpq5 git \
  && rm -rf /var/lib/apt/lists/*

COPY --from=builder /venv /venv
COPY --from=builder /app /app

# 可选：构建时注入分支/提交，供每日摘要等展示（镜像内通常无 git）
ARG MODSTORE_GIT_BRANCH=
ARG MODSTORE_GIT_COMMIT=
RUN if [ -n "$MODSTORE_GIT_BRANCH$MODSTORE_GIT_COMMIT" ]; then \
    printf '%s\n' "{\"branch\":\"${MODSTORE_GIT_BRANCH}\",\"commit\":\"${MODSTORE_GIT_COMMIT}\"}" \
      > /app/.modstore_build.json; \
  fi

EXPOSE 8765

CMD ["python", "-m", "uvicorn", "modstore_server.app:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "4"]
