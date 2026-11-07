import assert from 'node:assert/strict'
import { test } from 'node:test'
import { brandAndSocialMetadata } from './metadata.mjs'

test('preserves a page-specific description when rebuilding social metadata', () => {
  const description = '独有案例：校园选课流程与 Excel 导入校验。'
  const result = brandAndSocialMetadata(`<head>
    <title>行业案例 | XCMAX</title>
    <meta name="description" content="${description}" />
    <meta property="og:description" content="obsolete description" />
    <meta name="twitter:description" content="obsolete description" />
    <link rel="canonical" href="https://old.example/" />
    <link rel="icon" href="/old.ico" />
  </head>`, 'cases.html')

  assert.ok(result.includes('<title>行业案例 | XCAGI</title>'))
  assert.ok(result.includes(`<meta name="description" content="${description}" />`))
  assert.ok(result.includes(`<meta property="og:description" content="${description}" />`))
  assert.ok(result.includes('<link rel="canonical" href="https://xiu-ci.com/cases.html" />'))
  assert.ok(!result.includes('obsolete description'))
  for (const marker of ['name="description"', 'property="og:description"', 'rel="canonical"', 'rel="icon"']) {
    assert.equal(result.split(marker).length - 1, 1)
  }
})

test('repeated metadata builds preserve entities and produce identical HTML', () => {
  const head = `<head>
    <title>R&D &amp; "团队" $& &#39; &lt;企划&gt; | XCMAX</title>
    <meta name="description" content="专属 A&B &amp; C &quot;备注&quot; &#39; &#x4e2d; &copy; &lt;表格&gt;" />
  </head>`
  const first = brandAndSocialMetadata(head, 'index.html')
  const second = brandAndSocialMetadata(first, 'index.html')

  assert.ok(first.includes('<title>R&amp;D &amp; &quot;团队&quot; $&amp; &#39; &lt;企划&gt; | XCAGI</title>'))
  assert.ok(first.includes('content="专属 A&amp;B &amp; C &quot;备注&quot; &#39; &#x4e2d; &copy; &lt;表格&gt;"'))
  assert.equal(second, first)
  assert.equal(brandAndSocialMetadata(second, 'index.html'), first)
})

test('retains the default description for pages without one', () => {
  const result = brandAndSocialMetadata('<head><title>产品中心</title></head>', 'services.html')
  assert.ok(result.includes('<title>产品中心 | XCAGI</title>'))
  assert.ok(result.includes('<meta name="description" content="XCAGI 企业业务自动化平台：围绕考勤、销售、客服、ERP、Excel 单据和企业流程开展自动化。" />'))
})
