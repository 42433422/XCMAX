# 微信电话对接业务员运维手册

## 故障排查
- phone-agent 启动失败：检查 Mod 服务 sz-qsm-pro 是否部署、API 是否可达
- 来电未接听：检查 Win32 窗口监控权限与微信版本
- ASR 转写失败：检查音频采集设备与 VB-Cable 配置
- TTS 播报失败：检查 TTS 服务与音频输出设备

## 关键 API
- POST /api/mod/sz-qsm-pro/phone-agent/start
- POST /api/mod/sz-qsm-pro/phone-agent/stop
- GET /api/mod/sz-qsm-pro/phone-agent/status
