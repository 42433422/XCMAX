# Skill: 语音转写与回复播报

## 能力描述
来电接听后采集音频、ASR 转写、意图识别、TTS 回复播报。

## 触发条件
- phone-agent 检测到来电并自动接听

## 执行步骤
1. 来电后自动点击接听
2. 音频采集（VB-Cable 虚拟音频线）
3. ASR 实时转写
4. 意图识别与回复生成
5. TTS 播报回复

## 输入格式
```json
{
  "action": "on_call",
  "caller": "客户号码",
  "auto_answer": true
}
```
