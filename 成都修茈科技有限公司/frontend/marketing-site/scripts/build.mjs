/**
 * Builds root-level marketing HTML from templates + JSON.
 * Outputs to repository root next to marketing-site/.
 */
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import nunjucks from 'nunjucks'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SITE_DIR = path.join(__dirname, '..')
const REPO_ROOT = path.join(SITE_DIR, '..')
const TEMPLATE_DIR = path.join(SITE_DIR, 'templates')
const DATA_DIR = path.join(SITE_DIR, 'data')
const ASSET_VER = '20260925a'
/** @type {{ file: string, activeNav: string }[]} */
const WRAP_PAGES = [
  { file: 'index.html', activeNav: 'home' },
  { file: 'about.html', activeNav: 'about' },
  { file: 'visualization.html', activeNav: 'visualization' },
  { file: 'services.html', activeNav: 'services' },
  { file: 'solutions.html', activeNav: 'solutions' },
  { file: 'cases.html', activeNav: 'cases' },
  { file: 'contact.html', activeNav: 'contact' },
  { file: 'developer.html', activeNav: 'developer' },
  { file: 'world-will.html', activeNav: 'world-will' },
  { file: 'honors.html', activeNav: 'honors' },
  { file: 'case-edu.html', activeNav: 'cases' },
  { file: 'case-manufacture.html', activeNav: 'cases' },
  { file: 'case-coating.html', activeNav: 'cases' },
  { file: 'case-park.html', activeNav: 'cases' },
]

const nun = nunjucks.configure(TEMPLATE_DIR, { autoescape: true, noCache: true })

function readNewsData() {
  const p = path.join(DATA_DIR, 'news.json')
  const raw = fs.readFileSync(p, 'utf8')
  return JSON.parse(raw)
}

function readCapabilityData() {
  return JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'data', 'capabilities.json'), 'utf8'))
}

function materializePlatformStatuses(html, data) {
  for (const [platform, level] of Object.entries(data.platform_levels || {})) {
    const escapedPlatform = platform.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const safeLevel = String(level).replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    html = html.replace(
      new RegExp(`(data-platform-status="${escapedPlatform}"[^>]*>)[^<]*(</[^>]+>)`, 'g'),
      `$1${safeLevel}$2`,
    )
  }
  return html
}

function normalizeNews(items) {
  return [...items].sort((a, b) => (b.date || '').localeCompare(a.date || ''))
}

/** @param {string} html */
function extractShellParts(html) {
  const headMatch = html.match(/^<!DOCTYPE[\s\S]*?<\/head>/i)
  const mainMatch = html.match(/<main[\s\S]*?<\/main>/i)
  const footerMatch = html.match(/<footer[\s\S]*?<\/footer>/i)
  if (!headMatch || !mainMatch || !footerMatch) {
    throw new Error('Could not extract <head>, <main>, or <footer>')
  }
  return {
    headHtml: headMatch[0],
    mainHtml: mainMatch[0],
    footerHtml: footerMatch[0],
  }
}

function buildNews(newsItems) {
  const sorted = normalizeNews(newsItems)
  const html = nun.render('news-page.njk', {
    newsItems: sorted,
    cssQuery: ASSET_VER,
    assetVer: ASSET_VER,
  })
  fs.writeFileSync(path.join(REPO_ROOT, 'news.html'), html, 'utf8')
  fs.copyFileSync(path.join(DATA_DIR, 'news.json'), path.join(REPO_ROOT, 'news.json'))
}

/** @param {string} headHtml */
function bumpStylesInHead(headHtml, ver = ASSET_VER) {
  return headHtml.replace(/styles\.css\?v=[^"'>\s]+/g, `styles.css?v=${ver}`)
}

function brandAndSocialMetadata(headHtml, file) {
  headHtml = headHtml
    .replace(/\s*<meta\s+(?:property="og:[^"]+"|name="twitter:[^"]+"|name="description")[^>]*>/gi, '')
    .replace(/\s*<link\s+rel="canonical"[^>]*>/gi, '')
    .replace(/\s*<link\s+rel="icon"[^>]*>/gi, '')
  let title = headHtml.match(/<title>([\s\S]*?)<\/title>/i)?.[1]?.replace(/XCMAX/gi, 'XCAGI').trim() || 'XCAGI 企业业务自动化平台'
  if (!title.includes('XCAGI')) title = `${title} | XCAGI`
  const description = headHtml.match(/<meta\s+name="description"[^>]*content="([^"]*)"[^>]*>/i)?.[1] || 'XCAGI 企业业务自动化平台：围绕考勤、销售、客服、ERP、Excel 单据和企业流程开展自动化。'
  const canonical = `https://xiu-ci.com/${file === 'index.html' ? '' : file}`
  const safeTitle = title.replaceAll('&', '&amp;').replaceAll('"', '&quot;')
  const safeDescription = description.replaceAll('&', '&amp;').replaceAll('"', '&quot;')
  const tags = `<meta name="description" content="${safeDescription}" />\n    <meta property="og:site_name" content="XCAGI" />\n    <meta property="og:title" content="${safeTitle}" />\n    <meta property="og:description" content="${safeDescription}" />\n    <meta property="og:type" content="website" />\n    <meta property="og:url" content="${canonical}" />\n    <meta property="og:image" content="https://xiu-ci.com/assets/brand-logo.jpg" />\n    <meta name="twitter:card" content="summary_large_image" />\n    <link rel="canonical" href="${canonical}" />\n    <link rel="icon" href="/assets/xiu-ci-logo.png" type="image/png" />`
  return headHtml.replace(/<title>[\s\S]*?<\/title>/i, `<title>${safeTitle}</title>`).replace(/<\/head>/i, `    ${tags}\n  </head>`)
}

function wrapPages(capabilityData) {
  for (const { file, activeNav } of WRAP_PAGES) {
    const srcPath = path.join(REPO_ROOT, file)
    if (!fs.existsSync(srcPath)) {
      console.warn(`skip missing ${file}`)
      continue
    }
    const raw = fs.readFileSync(srcPath, 'utf8')
    const { headHtml, mainHtml, footerHtml } = extractShellParts(raw)
    const html = nun.render('shell.njk', {
      activeNav,
      headHtml: brandAndSocialMetadata(bumpStylesInHead(headHtml), file),
      mainHtml,
      footerHtml,
      assetVer: ASSET_VER,
      bodyAttrs:
        activeNav === 'home'
          ? 'data-page="index"'
          : activeNav === 'world-will'
            ? 'data-page="world-will"'
            : activeNav === 'contact'
              ? 'class="page-contact"'
              : '',
    })
    fs.writeFileSync(srcPath, materializePlatformStatuses(html, capabilityData), 'utf8')
  }
}

function main() {
  const newsItems = readNewsData()
  const capabilityData = readCapabilityData()
  buildNews(newsItems)
  wrapPages(capabilityData)
  const downloadPath = path.join(REPO_ROOT, 'download.html')
  const downloadHtml = fs.readFileSync(downloadPath, 'utf8')
  fs.writeFileSync(downloadPath, materializePlatformStatuses(downloadHtml, capabilityData), 'utf8')
  console.log('marketing-site build: wrote news.html + news.json, re-wrapped', WRAP_PAGES.length, 'pages')
}

main()
