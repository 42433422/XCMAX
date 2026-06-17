const { execFileSync } = require('node:child_process');
const path = require('node:path');

/**
 * electron-builder hook: regenerate NSIS bitmaps + icon assets before pack.
 * See desktop/resources/README.md
 */
exports.default = async function beforePack() {
  const root = path.resolve(__dirname, '../..');
  const py = process.platform === 'win32' ? 'python' : 'python3';
  const script = path.join(root, 'scripts/package/generate-desktop-resources.py');
  const env = {
    ...process.env,
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
  };
  execFileSync(py, ['-m', 'pip', 'install', 'Pillow>=10.2.0', '-q'], {
    cwd: root,
    env,
    stdio: 'inherit',
  });
  execFileSync(py, [script], { cwd: root, env, stdio: 'inherit' });
};
