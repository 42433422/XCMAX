const fs = require('node:fs')
const path = require('node:path')

const projectRoot = path.resolve(__dirname, '..')
const source = path.join(projectRoot, 'resources', 'splash.html')
const outputDir = path.join(projectRoot, 'dist')
const destination = path.join(outputDir, 'splash.html')

fs.mkdirSync(outputDir, { recursive: true })
fs.copyFileSync(source, destination)
console.log(`[desktop-build] copied ${source} -> ${destination}`)
