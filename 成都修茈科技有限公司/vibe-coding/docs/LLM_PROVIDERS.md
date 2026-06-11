# LLM Provider Adapters

vibe-coding ships ready-made `LLMClient` implementations for the
providers most users reach for first. Anything else with an
OpenAI-compatible HTTP endpoint (vLLM, Ollama, LMStudio,
together.ai, your own gateway) works out of the box via
`OpenAICompatibleLLM`.

| Vendor | Class | Default endpoint | API key env var |
| --- | --- | --- | --- |
| OpenAI | `OpenAILLM` (SDK-backed) | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| Alibaba 通义千问 | `QwenLLM` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` (or `QWEN_API_KEY`) |
| 智谱 GLM | `ZhipuLLM` | `https://open.bigmodel.cn/api/paas/v4` | `ZHIPUAI_API_KEY` |
| Moonshot Kimi | `MoonshotLLM` | `https://api.moonshot.cn/v1` | `MOONSHOT_API_KEY` (or `KIMI_API_KEY`) |
| DeepSeek | `DeepSeekLLM` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |
| Anthropic Claude | `AnthropicLLM` | `https://api.anthropic.com/v1` | `ANTHROPIC_API_KEY` |
| Anything OpenAI-compatible | `OpenAICompatibleLLM` | (set `base_url`) | (set `api_key`) |

## Quick start

```python
from vibe_coding import VibeCoder, create_llm

# By model id (prefix detection picks the right vendor):
llm = create_llm("qwen-max", api_key="sk-...")
llm = create_llm("glm-4")
llm = create_llm("kimi", model="moonshot-v1-128k")
llm = create_llm("claude-3-5-sonnet-latest")

# Or by alias:
llm = create_llm("dashscope")     # → QwenLLM(default model)
llm = create_llm("zhipu")         # → ZhipuLLM(default model)
llm = create_llm("deepseek")      # → DeepSeekLLM(default model)

# Self-hosted vLLM / Ollama / LMStudio (anything OpenAI-compatible):
llm = create_llm(
    "my-finetuned-model",
    api_key="sk-ignored",
    base_url="http://192.168.1.10:8000/v1",
)

coder = VibeCoder(llm=llm, store_dir="./data")
skill = coder.code("Reverse a string")
```

## Provider auto-detection

`create_llm("model-or-alias", api_key=..., base_url=...)` picks the
right adapter via:

1. **Alias match** — `"qwen"`, `"kimi"`, `"glm"`, `"deepseek"`,
   `"claude"`, `"openai"`, `"tongyi"`, `"dashscope"`, etc. The
   provider's default model is used unless `model=` is passed.
2. **Model-id prefix** — `qwen-`, `glm-`, `moonshot-`, `kimi-`,
   `deepseek-`, `claude-`, `gpt-` → matching adapter.
3. **Fallback** — unknown ids fall through to
   `OpenAICompatibleLLM(model=…, base_url=…)` so any vendor with the
   standard `/v1/chat/completions` shape works.

## Custom providers

```python
from vibe_coding.nl.providers import register_provider, ProviderInfo
from vibe_coding.nl.providers.openai_compat import OpenAICompatibleLLM


class CorpGatewayLLM(OpenAICompatibleLLM):
    default_base_url = "https://gateway.corp.example/v1"


register_provider(
    ProviderInfo(
        name="corp",
        factory=CorpGatewayLLM,
        aliases=("corp",),
        model_prefixes=("corp-",),
        default_model="corp-coder-13b",
    )
)

llm = create_llm("corp", api_key="...")
```

## Env-var fallback

Every adapter falls back to its conventional env var when `api_key=` is
omitted. This makes it safe to commit code like:

```python
from vibe_coding import create_llm

# In dev: rely on the export from your shell.
# In CI: set DASHSCOPE_API_KEY in the secrets store.
llm = create_llm("qwen-max")
```

## JSON mode

`json_mode=True` (the default) is honoured natively by OpenAI / Qwen /
Zhipu / Moonshot / DeepSeek (they all support `response_format`).
Anthropic's API doesn't have a JSON-mode flag — we strengthen the
system prompt and post-process the reply to strip Markdown fences
before returning it. Either way, vibe-coding's tolerant
`safe_parse_json_object` parser handles whatever the vendor produces.

## Observability

When you wrap a provider via `vibe_coding.agent.observability.instrument(coder)`,
every `chat()` call gets a span and a histogram observation
(`vibe_coder_action_duration_ms{method="..."}`). Counters distinguish
success vs. error, so you can plot "qwen 5xx rate" or "claude p99
latency" off the bundled `/metrics` endpoint.
