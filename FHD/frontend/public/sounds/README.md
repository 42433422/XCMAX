# IM 提示音

用户可见的 IM 收发提示音（Web/桌面共用，缺失时回退到 WebAudio 短哔声）：

- `im-in.wav` — 收到消息
- `im-send.wav` — 发送成功

## 来源与许可

两段音效取自 [Zulip](https://github.com/zulip/zulip) 的 `static/audio/notification_sounds/`（Apache-2.0 仓库）：

| 文件 | 上游文件 | 版权 | 许可 |
|------|----------|------|------|
| `im-in.wav` | `friendly.mp3` | 2021 Stefan Mertens | CC0-1.0（公有领域，可商用） |
| `im-send.wav` | `swish.mp3` | 2021 Stefan Mertens | CC0-1.0（公有领域，可商用） |

依据 Zulip 的 `docs/THIRDPARTY`：`static/audio/notification_sounds/*` 为 CC0-1.0，仅 `ding.*` 为 CC-BY-3.0（未采用）。
转换方式：`afconvert -f WAVE -d LEI16@44100 -c 1`，单声道 44.1kHz，时长分别约 0.39s / 0.19s。

替换时保持文件名不变即可，无需改代码。
