// Source declarations only; loading a route/component still requires runtime evidence.
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('../..', import.meta.url)))
const require = createRequire(resolve(root, 'frontend/package.json'))
const ts = require('typescript')
const { parse } = require('@vue/compiler-sfc')
const { parse: parseTemplate } = require('@vue/compiler-dom')
const input = []
for await (const chunk of process.stdin) input.push(chunk)
const files = JSON.parse(Buffer.concat(input).toString('utf8'))
const result = { routes: [], events: [], file_inputs: [], errors: [] }
for (const file of files) {
  const source = readFileSync(resolve(root, file), 'utf8')
  let scripts = [{ content: source, offset: 0 }]
  if (file.endsWith('.vue')) {
    const parsed = parse(source, { filename: file })
    if (parsed.errors.length) result.errors.push({ source: file, reason: 'vue_parse_error' })
    scripts = [parsed.descriptor.script, parsed.descriptor.scriptSetup].filter(Boolean)
      .map(script => ({ content: script.content, offset: script.loc.start.offset }))
    const template = parsed.descriptor.template
    if (template) {
      try {
        const visitTemplate = (node) => {
          if (node.type === 1) {
            const line = source.slice(0, template.loc.start.offset + node.loc.start.offset).split('\n').length
            const item = { source: file, line, tag: node.tag }
            for (const prop of node.props) {
              if (prop.type === 7 && prop.name === 'on') {
                result.events.push({ ...item, event: prop.arg?.content ?? '*dynamic*', handler: prop.exp?.content ?? '' })
              }
            }
            const fileType = node.props.some(prop => prop.type === 6 && prop.name === 'type' && prop.value?.content === 'file')
            const dynamicType = node.props.some(prop => prop.type === 7 && prop.name === 'bind' && prop.arg?.content === 'type')
            if ((node.tag === 'input' && (fileType || dynamicType)) || /(?:^|-)upload$/i.test(node.tag)) {
              result.file_inputs.push({ ...item, certainty: fileType ? 'native_file_input' : dynamicType ? 'dynamic_input_type' : 'upload_component' })
            }
          }
          for (const child of node.children ?? []) visitTemplate(child)
        }
        visitTemplate(parseTemplate(template.content))
      } catch { result.errors.push({ source: file, reason: 'template_parse_error' }) }
    }
  }
  for (const script of scripts) {
    const tree = ts.createSourceFile(file, script.content, ts.ScriptTarget.Latest, true, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
    if (tree.parseDiagnostics.length) result.errors.push({ source: file, reason: 'script_parse_error' })
    const visit = (node) => {
      if (ts.isObjectLiteralExpression(node)) {
        const properties = new Map(node.properties.filter(ts.isPropertyAssignment).map(prop => [prop.name.getText(tree).replace(/^['"]|['"]$/g, ''), prop.initializer]))
        const path = properties.get('path')
        if (path && ['component', 'components', 'redirect', 'children'].some(name => properties.has(name))) {
          const literal = ts.isStringLiteralLike(path)
          result.routes.push({
            source: file,
            line: source.slice(0, script.offset + node.getStart(tree)).split('\n').length,
            declared_path: literal ? path.text : path.getText(tree),
            dynamic: !literal,
            mount_status: 'unverified',
          })
        }
      }
      ts.forEachChild(node, visit)
    }
    visit(tree)
  }
}
process.stdout.write(JSON.stringify(result))
