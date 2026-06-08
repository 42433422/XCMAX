/**
 * 办公生成员：纯文本 / 用户 JSON 附件 → 生成阶段输入。
 */
import type { OfficeFormat } from './officeEmployeeOrchestration'

export type GenerateInputResolveOptions = {
  format: OfficeFormat
  userText: string
  attachmentFiles?: File[]
}

export type ResolvedGenerateInputs = {
  jsonFile: File
  inputData: Record<string, unknown>
  usedUserJson: boolean
}

export function detectUserProvidedJsonFile(files: File[]): File | null {
  for (const f of files) {
    const name = String(f.name || '').toLowerCase()
    if (name.endsWith('.json') && f.type !== 'application/json') {
      // keep going — type may be empty in some browsers
    }
    if (name.endsWith('.json')) return f
  }
  return null
}

/** 最小 JSON：后端 office_plaintext_generate 会扩写为完整 schema（含 LLM）。 */
export function buildGenerateJsonFile(format: OfficeFormat, userText: string): File {
  const text = String(userText || '').trim()
  const body: Record<string, unknown> = {
    user_query: text,
    plain_text: text,
    format,
    source: 'workbench_plaintext',
  }
  if (format === 'ppt') {
    body.title = text.split('\n')[0]?.slice(0, 120) || '演示文稿'
  }
  return new File([JSON.stringify(body, null, 2)], 'generate_input.json', {
    type: 'application/json',
  })
}

export function resolveGenerateInputs(opts: GenerateInputResolveOptions): ResolvedGenerateInputs {
  const userJson = detectUserProvidedJsonFile(opts.attachmentFiles || [])
  if (userJson) {
    return {
      jsonFile: userJson,
      inputData: {
        user_query: opts.userText || '',
        use_llm_from_text: false,
      },
      usedUserJson: true,
    }
  }
  const useLlm = opts.format === 'excel' || opts.format === 'ppt'
  return {
    jsonFile: buildGenerateJsonFile(opts.format, opts.userText),
    inputData: {
      user_query: opts.userText || '',
      plain_text: opts.userText || '',
      use_llm_from_text: useLlm,
      skip_llm: !useLlm,
    },
    usedUserJson: false,
  }
}
