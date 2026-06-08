/** 仅 UI 元数据；真实模型列表来自 GET /api/llm/catalog */

export const LLM_UI_META = {
  openai: {
    id: 'openai',
    label: 'OpenAI',
    iconSlug: 'openai',
    doc: 'https://platform.openai.com/docs/api-reference',
  },
  anthropic: {
    id: 'anthropic',
    label: 'Anthropic',
    iconSlug: 'anthropic',
    doc: 'https://docs.anthropic.com/en/api',
  },
  google: {
    id: 'google',
    label: 'Google Gemini',
    iconSlug: 'googlegemini',
    doc: 'https://ai.google.dev/gemini-api/docs',
  },
  deepseek: {
    id: 'deepseek',
    label: 'DeepSeek',
    iconSlug: 'deepseek',
    doc: 'https://api-docs.deepseek.com',
  },
  siliconflow: {
    id: 'siliconflow',
    label: 'SiliconFlow',
    iconSlug: 'huggingface',
    doc: 'https://docs.siliconflow.cn',
  },
  xiaomi: {
    id: 'xiaomi',
    label: '小米 MiMo',
    iconSlug: 'xiaomi',
    doc: 'https://platform.xiaomimimo.com/',
  },
  groq: {
    id: 'groq',
    label: 'Groq',
    iconSlug: 'groq',
    doc: 'https://console.groq.com/docs',
  },
  together: {
    id: 'together',
    label: 'Together AI',
    iconSlug: 'togethercomputer',
    doc: 'https://docs.together.ai',
  },
  openrouter: {
    id: 'openrouter',
    label: 'OpenRouter',
    iconSlug: 'openrouter',
    doc: 'https://openrouter.ai/docs',
  },
  dashscope: {
    id: 'dashscope',
    label: '阿里云百炼',
    iconSlug: 'alibabacloud',
    doc: 'https://help.aliyun.com/zh/model-studio/developer-reference/use-qwen-by-calling-api',
  },
  moonshot: {
    id: 'moonshot',
    label: '月之暗面 Kimi',
    iconSlug: 'openai',
    doc: 'https://platform.moonshot.cn/docs',
  },
  minimax: {
    id: 'minimax',
    label: 'MiniMax',
    iconSlug: 'minimax',
    doc: 'https://platform.minimaxi.com/document/guides/chat-model/V2',
  },
  doubao: {
    id: 'doubao',
    label: '豆包',
    iconSlug: 'bytedance',
    doc: 'https://www.volcengine.com/docs/82379/1330626',
  },
  wenxin: {
    id: 'wenxin',
    label: '百度文心 / 千帆',
    iconSlug: 'baidu',
    doc: 'https://cloud.baidu.com/doc/WENXINWORKSHOP/index.html',
  },
  hunyuan: {
    id: 'hunyuan',
    label: '腾讯混元',
    iconSlug: 'tencentqq',
    doc: 'https://cloud.tencent.com/document/product/1729',
  },
  zhipu: {
    id: 'zhipu',
    label: '智谱 GLM',
    iconSlug: 'openai',
    doc: 'https://open.bigmodel.cn/dev/api',
  },
  xunfei: {
    id: 'xunfei',
    label: '讯飞星火',
    iconSlug: 'ifttt',
    doc: 'https://www.xfyun.cn/doc/spark/Web.html',
  },
  yi: {
    id: 'yi',
    label: '零一万物',
    iconSlug: 'openai',
    doc: 'https://platform.lingyiwanwu.com/docs',
  },
  stepfun: {
    id: 'stepfun',
    label: '阶跃星辰',
    iconSlug: 'openai',
    doc: 'https://platform.stepfun.com/docs',
  },
  baichuan: {
    id: 'baichuan',
    label: '百川智能',
    iconSlug: 'openai',
    doc: 'https://platform.baichuan-ai.com/docs',
  },
  sensetime: {
    id: 'sensetime',
    label: '商汤日日新',
    iconSlug: 'openai',
    doc: 'https://platform.sensenova.cn',
  },
}

export function llmUiMeta(providerId: string) {
  return (
    (LLM_UI_META as Record<string, (typeof LLM_UI_META)[keyof typeof LLM_UI_META] | undefined>)[providerId] || {
      id: providerId,
      label: providerId,
      iconSlug: 'openai',
      doc: '#',
    }
  )
}

/** 可在 BYOK 中填写自定义 Base URL 的 OpenAI 兼容厂商 */
export const LLM_OAI_COMPAT_BASE_URL_PROVIDERS = [
  'openai',
  'deepseek',
  'siliconflow',
  'xiaomi',
  'groq',
  'together',
  'openrouter',
  'dashscope',
  'moonshot',
  'minimax',
  'doubao',
  'wenxin',
  'hunyuan',
  'zhipu',
  'xunfei',
  'yi',
  'stepfun',
  'baichuan',
  'sensetime',
]
