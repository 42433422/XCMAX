#!/usr/bin/env node
/**
 * 解析 electronegativity CSV 报告,按严重程度统计并执行门禁。
 *
 * 用法:
 *   node parse-electronegativity-csv.js <csv-path> [--gate-severity high|medium|low]
 *
 * 默认门禁: 任何 HIGH 严重程度 finding 即失败(exit 1)。
 * 输出: 写入 $GITHUB_STEP_SUMMARY(若存在),并在 stdout 打印统计。
 *
 * CSV 列(来自 electronegativity src/util/file.js):
 *   issue, severity, confidence, filename, location, sample, description, url
 * severity 取值: HIGH | MEDIUM | LOW | INFORMATIONAL
 */
'use strict'

const fs = require('node:fs')
const path = require('node:path')

function parseArgs(argv) {
  const args = argv.slice(2)
  if (args.length === 0) {
    console.error('用法: parse-electronegativity-csv.js <csv-path> [--gate-severity high|medium|low]')
    process.exit(2)
  }
  const csvPath = args[0]
  let gateSeverity = 'high'
  for (let i = 1; i < args.length; i++) {
    if (args[i] === '--gate-severity' && args[i + 1]) {
      gateSeverity = String(args[i + 1]).toLowerCase()
      i++
    }
  }
  const order = { high: 3, medium: 2, low: 1, informational: 0 }
  if (!(gateSeverity in order)) {
    console.error(`--gate-severity 取值无效: ${gateSeverity} (应为 high|medium|low|informational)`)
    process.exit(2)
  }
  return { csvPath, gateSeverity, gateLevel: order[gateSeverity] }
}

// 解析单行 CSV,处理双引号转义("")。返回字段数组,空行返回 null。
function parseCsvLine(line) {
  if (line === '') return null
  const fields = []
  let i = 0
  while (i < line.length) {
    if (line[i] === '"') {
      let value = ''
      i++
      while (i < line.length) {
        if (line[i] === '"') {
          if (line[i + 1] === '"') {
            value += '"'
            i += 2
          } else {
            i++
            break
          }
        } else {
          value += line[i]
          i++
        }
      }
      fields.push(value)
      if (line[i] === ',') i++
    } else {
      let value = ''
      while (i < line.length && line[i] !== ',') {
        value += line[i]
        i++
      }
      fields.push(value)
      if (line[i] === ',') i++
    }
  }
  return fields
}

function severityLevel(name) {
  const order = { high: 3, medium: 2, low: 1, informational: 0 }
  return order[String(name).trim().toLowerCase()] ?? -1
}

function main() {
  const { csvPath, gateSeverity, gateLevel } = parseArgs(process.argv)
  if (!fs.existsSync(csvPath)) {
    console.error(`CSV 文件不存在: ${csvPath}`)
    process.exit(2)
  }
  const raw = fs.readFileSync(csvPath, 'utf8')
  const lines = raw.split(/\r?\n/)

  // 第一行是表头: issue, severity, confidence, filename, location, sample, description, url
  if (lines.length === 0) {
    console.error('CSV 为空')
    process.exit(2)
  }
  const header = parseCsvLine(lines[0])
  if (!header || header.length < 8) {
    console.error(`CSV 表头异常: ${lines[0]}`)
    process.exit(2)
  }

  const findings = []
  for (let i = 1; i < lines.length; i++) {
    const fields = parseCsvLine(lines[i])
    if (!fields || fields.length < 8) continue
    const [issue, severity, confidence, filename, location, sample, description, url] = fields
    findings.push({ issue, severity, confidence, filename, location, sample, description, url })
  }

  const counts = { HIGH: 0, MEDIUM: 0, LOW: 0, INFORMATIONAL: 0 }
  const byId = new Map()
  for (const f of findings) {
    const sev = String(f.severity).toUpperCase()
    if (sev in counts) counts[sev]++
    else counts.INFORMATIONAL++
    if (!byId.has(f.issue)) byId.set(f.issue, { count: 0, severity: sev, description: f.description, url: f.url })
    byId.get(f.issue).count++
  }

  const blocking = findings.filter(f => severityLevel(f.severity) >= gateLevel)

  // 输出到 GitHub Step Summary(若可用)
  const stepSummaryPath = process.env.GITHUB_STEP_SUMMARY
  const summaryLines = []
  summaryLines.push('## Electronegativity 安全扫描报告')
  summaryLines.push('')
  summaryLines.push(`扫描文件: \`${path.relative(process.cwd(), csvPath)}\``)
  summaryLines.push(`门禁阈值: **${gateSeverity.toUpperCase()}** 及以上即失败`)
  summaryLines.push('')
  summaryLines.push('### 严重程度分布')
  summaryLines.push('')
  summaryLines.push('| 严重程度 | 数量 |')
  summaryLines.push('|----------|------|')
  summaryLines.push(`| HIGH | ${counts.HIGH} |`)
  summaryLines.push(`| MEDIUM | ${counts.MEDIUM} |`)
  summaryLines.push(`| LOW | ${counts.LOW} |`)
  summaryLines.push(`| INFORMATIONAL | ${counts.INFORMATIONAL} |`)
  summaryLines.push(`| **合计** | **${findings.length}** |`)
  summaryLines.push('')

  if (byId.size > 0) {
    summaryLines.push('### 按检查 ID 汇总')
    summaryLines.push('')
    summaryLines.push('| 检查 ID | 严重程度 | 命中数 | 描述 |')
    summaryLines.push('|---------|----------|--------|------|')
    for (const [id, info] of byId) {
      const desc = (info.description || '').replace(/\|/g, '\\|').slice(0, 120)
      summaryLines.push(`| ${id} | ${info.severity} | ${info.count} | ${desc} |`)
    }
    summaryLines.push('')
  }

  if (blocking.length > 0) {
    summaryLines.push(`### ❌ 门禁失败: ${blocking.length} 个 ${gateSeverity.toUpperCase()}+ finding`)
    summaryLines.push('')
    summaryLines.push('| 文件 | 位置 | 检查 ID | 严重程度 | 描述 |')
    summaryLines.push('|------|------|---------|----------|------|')
    for (const f of blocking) {
      const desc = (f.description || '').replace(/\|/g, '\\|').slice(0, 100)
      const fname = (f.filename || '').replace(/\|/g, '\\|')
      summaryLines.push(`| ${fname} | ${f.location} | ${f.issue} | ${f.severity} | ${desc} |`)
    }
  } else {
    summaryLines.push(`### ✅ 门禁通过: 无 ${gateSeverity.toUpperCase()}+ finding`)
  }

  const summary = summaryLines.join('\n')
  if (stepSummaryPath) {
    fs.appendFileSync(stepSummaryPath, summary + '\n')
  }
  console.log(summary)
  console.log('')

  if (blocking.length > 0) {
    console.error(`❌ electronegativity 门禁失败: ${blocking.length} 个 ${gateSeverity.toUpperCase()}+ finding`)
    process.exit(1)
  }
  console.log(`✅ electronegativity 门禁通过 (阈值 ${gateSeverity.toUpperCase()}, 总计 ${findings.length} findings)`)
}

main()
