# 桌面密钥包导出（Web → 本地）

将多条 Personal Access Token **加密**下发到桌面软件，避免在浏览器中逐条复制明文。

## 流程概览

1. **桌面端**生成 **P-256（secp256r1）** 密钥对，导出公钥为 **DER SubjectPublicKeyInfo**，再 **Base64** 编码。
2. 用户在网页 **开发者门户 → API Token** 中粘贴公钥，勾选要下发的 Token，输入**当前登录密码**确认。
3. 服务端对所选 Token **轮换签发**（旧 Token 吊销，同名同 scope 新明文仅出现在密文中），用 ECDH + HKDF + AES-256-GCM 封装为二进制包，浏览器下载 **`.msk1`** 文件。
4. 桌面端用私钥解密，得到 JSON（含 `tokens[].token` 等字段），写入本地钥匙串。

## 密文格式

算法标识：`ECDH_SECP256R1_AES256GCM`。二进制布局见服务端 `modstore_server/key_export_crypto.py` 中注释（魔数 `MSK1`、版本、临时公钥、nonce、密文）。

## API

- `POST /api/developer/key-export/bundle`  
  Body: `recipient_public_key_spki_b64`, `current_password`, `token_ids`, `rotate_source_tokens`（默认 `true`，当前仅支持 `true`）。  
  Response: `cipher_b64`, `algorithm`, `token_count`, `rotated_ids`。
- `GET /api/developer/key-export/audit`  
  当前用户导出审计（不含密钥）。

## 安全说明

- 传输使用 **HTTPS**。
- 导出受 **密码二次确认** 与 **每用户速率限制**（15 分钟内次数上限）约束。
- 审计表 `developer_key_export_events` 记录 IP、UA、动作、涉及 token id、成败，**不存明文**。

## Scope 与 Mod / 模型

推荐 scope 见 `modstore_server/developer_scopes.py`：`mod:sync`、`llm:use` 与既有 `catalog:read`、`employee:execute` 等组合，用于 Mod 同步与通过平台 Token 配置/调用模型能力（路由级强制校验将逐步对齐）。

## Python 解密示例（桌面侧）

```python
import base64
from modstore_server.key_export_crypto import decrypt_bundle_if_owned

priv_der = open("recipient.p8", "rb").read()  # PKCS8 DER 私钥
blob = open("bundle.msk1", "rb").read()
plain = decrypt_bundle_if_owned(priv_der, blob)
print(plain.decode("utf-8"))
```

生产环境请使用你桌面应用内的密钥存储，勿将私钥写入日志。
