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

/** 全站静态资源缓存版本（styles / main / corp-butler） */
const ASSET_VER = '20260619'

/** @type {{ file: string, activeNav: string }[]} */
const WRAP_PAGES = [
  { file: 'index.html', activeNav: 'home' },
  { file: 'about.html', activeNav: 'about' },
  { file: 'services.html', activeNav: 'services' },
  { file: 'solutions.html', activeNav: 'solutions' },
  { file: 'cases.html', activeNav: 'cases' },
  { file: 'contact.html', activeNav: 'contact' },
  { file: 'developer.html', activeNav: 'developer' },
  { file: 'honors.html', activeNav: 'honors' },
  { file: 'case-edu.html', activeNav: 'cases' },
  { file: 'case-manufacture.html', activeNav: 'cases' },
  { file: 'case-park.html', activeNav: 'cases' },
]

const nun = nunjucks.configure(TEMPLATE_DIR, { autoescape: true, noCache: true })

function readNewsData() {
  const p = path.join(DATA_DIR, 'news.json')
  const raw = fs.readFileSync(p, 'utf8')
  return JSON.parse(raw)
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

function wrapPages() {
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
      headHtml: bumpStylesInHead(headHtml),
      mainHtml,
      footerHtml,
      assetVer: ASSET_VER,
    })
    fs.writeFileSync(srcPath, html, 'utf8')
  }
}

function main() {
  const newsItems = readNewsData()
  buildNews(newsItems)
  wrapPages()
  console.log('marketing-site build: wrote news.html + news.json, re-wrapped', WRAP_PAGES.length, 'pages')
}

main()
