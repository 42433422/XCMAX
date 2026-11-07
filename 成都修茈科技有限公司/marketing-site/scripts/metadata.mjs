function escapeMetadata(value) {
  // Source metadata is already HTML: preserve its character references.
  return value.replace(/&(?!(?:#\d+|#x[\da-f]+|[a-z][a-z\d]*);)/gi, '&amp;')
    .replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

export function brandAndSocialMetadata(headHtml, file) {
  // Read the page's own metadata before removing the tags we regenerate.
  let title = headHtml.match(/<title>([\s\S]*?)<\/title>/i)?.[1]?.replace(/XCMAX/gi, 'XCAGI').trim() || 'XCAGI 企业业务自动化平台'
  if (!title.includes('XCAGI')) title = `${title} | XCAGI`
  const description = headHtml.match(/<meta\s+name="description"[^>]*content="([^"]*)"[^>]*>/i)?.[1] || 'XCAGI 企业业务自动化平台：围绕考勤、销售、客服、ERP、Excel 单据和企业流程开展自动化。'
  headHtml = headHtml
    .replace(/\s*<meta\s+(?:property="og:[^"]+"|name="twitter:[^"]+"|name="description")[^>]*>/gi, '')
    .replace(/\s*<link\s+rel="canonical"[^>]*>/gi, '')
    .replace(/\s*<link\s+rel="icon"[^>]*>/gi, '')
  const canonical = `https://xiu-ci.com/${file === 'index.html' ? '' : file}`
  const safeTitle = escapeMetadata(title)
  const safeDescription = escapeMetadata(description)
  const tags = `<meta name="description" content="${safeDescription}" />\n    <meta property="og:site_name" content="XCAGI" />\n    <meta property="og:title" content="${safeTitle}" />\n    <meta property="og:description" content="${safeDescription}" />\n    <meta property="og:type" content="website" />\n    <meta property="og:url" content="${canonical}" />\n    <meta property="og:image" content="https://xiu-ci.com/assets/brand-logo.jpg" />\n    <meta name="twitter:card" content="summary_large_image" />\n    <link rel="canonical" href="${canonical}" />\n    <link rel="icon" href="/assets/xiu-ci-logo.png" type="image/png" />`
  return headHtml.replace(/<title>[\s\S]*?<\/title>/i, () => `<title>${safeTitle}</title>`)
    .replace(/\s*<\/head>/i, () => `\n    ${tags}\n  </head>`)
}
