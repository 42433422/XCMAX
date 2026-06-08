# FunASR 语音识别部署

工作台「生成 Skill 组」等语音模式优先使用 FunASR 服务端识别。FunASR 需与本 MODstore API 同机或同 Docker 网络部署。

## 架构

```
浏览器 → wss://host/api/asr/funasr → modstore_server/asr_proxy_ws.py → ws://FUNASR_HOST:10095
```

若 FunASR 不可用，前端自动降级：Whisper 浏览器 Worker → Chrome Web Speech API。

## 快速部署（Docker）

```bash
docker pull registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-online-cpu-0.1.13

mkdir -p /data/funasr/models

docker run -d --name funasr --restart unless-stopped \
  -p 127.0.0.1:10095:10095 \
  -v /data/funasr/models:/workspace/models \
  registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-online-cpu-0.1.13 \
  bash -c 'cd FunASR/runtime && bash run_server_2pass.sh \
    --download-model-dir /workspace/models \
    --vad-dir damo/speech_fsmn_vad_zh-cn-16k-common-onnx \
    --model-dir damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-onnx \
    --online-model-dir damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online-onnx \
    --punc-dir damo/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727-onnx \
    --certfile 0'
```

或使用 Compose profile（推荐，容器以前台 exec 方式保活）：

```bash
docker compose --profile app up -d funasr
```

> **注意**：官方 `run_server_2pass.sh` 会用 `&` 后台启动后立即退出，Compose 容器会随之 Exit(0) 进入重启循环。本仓库 `docker-compose.yml` 已改为 `exec funasr-wss-server-2pass` 前台运行。

## 环境变量

在 `MODstore_deploy/.env` 中配置（API 进程须能读取）：

| 变量 | 说明 | 示例 |
|------|------|------|
| `FUNASR_HOST` | FunASR 地址；留空则自动尝试 `host.docker.internal` / `172.17.0.1` / `127.0.0.1` | `127.0.0.1` |
| `FUNASR_PORT` | WebSocket 端口 | `10095` |
| `FUNASR_USE_SSL` | `1` 使用 wss（FunASR 默认自签名证书）；`0` 使用 ws（`--certfile 0` 时） | `0` |

**systemd modstore（:9999）+ 宿主机 FunASR：**

```env
FUNASR_HOST=127.0.0.1
FUNASR_PORT=10095
FUNASR_USE_SSL=0
```

**Docker Compose api 容器 + compose funasr 服务：**

```env
FUNASR_HOST=funasr
FUNASR_PORT=10095
FUNASR_USE_SSL=0
```

修改后重启 API：

```bash
systemctl restart modstore
# 或
docker compose --profile app restart api
```

## Nginx WebSocket

`/api/asr/funasr` 必须使用带 `Upgrade` 的独立 location（与 `/api/realtime/` 相同），参见 `nginx-xiu-ci.conf` 与 `docs/nginx-https-example.conf`。

```nginx
location /api/asr/ {
    proxy_pass         http://127.0.0.1:9999;
    proxy_set_header   Upgrade $http_upgrade;
    proxy_set_header   Connection "upgrade";
    include /etc/nginx/snippets/proxy-forward-base.inc.conf;
    proxy_buffering    off;
    proxy_read_timeout 1d;
}
```

## 验证

```bash
# FunASR 监听
ss -tlnp | grep 10095

# 全链路冒烟
cd MODstore_deploy && set -a && source .env && set +a
python tools/smoke_voice_pipeline.py --asr-only
python tools/smoke_voice_pipeline.py
ASR_WS_URL=wss://xiu-ci.com/api/asr/funasr python tools/smoke_voice_pipeline.py --asr-only
cd market && npm run smoke:voice

# API 健康
curl -sS https://xiu-ci.com/api/health

# 查看 FunASR 日志
docker logs -f funasr --tail 50
```

浏览器：DevTools → Network → WS → `/api/asr/funasr?token=...` 应返回 101，说话后收到含 `text` 字段的 JSON。

## 故障排查

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| 「服务端语音识别不可用」 | systemd API 用了 `FUNASR_USE_SSL=1` 但 FunASR 为 ws；或 `FUNASR_HOST=funasr` 在宿主机无法解析 | 安装 `modstore-funasr.conf` drop-in，`FUNASR_HOST=127.0.0.1`、`FUNASR_USE_SSL=0`，`systemctl restart modstore` |
| 「FunASR 服务未启动」 | 未部署 / 端口不通 / `FUNASR_USE_SSL` 与 FunASR 协议不一致 | 检查 `ss -tlnp`、`.env`、`docker logs funasr` |
| 「语音识别无响应」 | nginx 缺 Upgrade；麦克风无权限；模型仍在下载 | 检查 nginx location；浏览器麦克风权限；等待模型下载完成 |
| Whisper `Failed to fetch` / CORS | 浏览器直连 hf-mirror 被 CORS 拦截 | 配置 nginx `location /hf-hub/` 反代 hf-mirror；前端经 `https://host/hf-hub/...` 拉模型 |
| 连接后立即断开 | JWT token 缺失或无效 | 确认已登录，`localStorage.modstore_token` 存在 |
| 首次启动极慢 | 模型下载 | 查看 `docker logs funasr`，确保磁盘 ≥ 5GB |

## 资源要求

- CPU：2 核以上推荐
- 内存：2–4 GB（模型加载后）
- 磁盘：模型约 2–3 GB
