"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
const node_child_process_1 = require("node:child_process");
const node_crypto_1 = __importDefault(require("node:crypto"));
const node_fs_1 = __importDefault(require("node:fs"));
const node_os_1 = require("node:os");
const node_path_1 = __importDefault(require("node:path"));
const updater_1 = require("./updater");
const APP_NAME = 'XCAGI';
/** macOS 12+「隔空播放接收器」占用 :5000，TCP 可达但返回 AirTunes 空 403 → Electron 白屏。 */
function resolveDefaultDesktopPort() {
    const env = process.env.XCAGI_DESKTOP_PORT;
    if (env) {
        return Number(env);
    }
    return process.platform === 'darwin' ? 17500 : 5000;
}
const DEFAULT_PORT = resolveDefaultDesktopPort();
const SKU_RUNTIME_EDITION = {
    personal: 'minimal',
    enterprise: 'full'
};
const SKU_UPDATE_URL = {
    personal: 'https://update.xcagi.com/releases/stable/personal/',
    enterprise: 'https://update.xcagi.com/releases/stable/enterprise/'
};
/** 企业版与网页 :5001 一致：完整侧栏，不强制 ?shell=1 */
function desktopInitialUrl() {
    const base = `http://127.0.0.1:${DEFAULT_PORT}/`;
    if (readPackagedProductSku() === 'enterprise') {
        return base;
    }
    return `${base}?shell=1`;
}
function readPackagedProductSku() {
    if (!electron_1.app.isPackaged)
        return null;
    const candidates = [
        node_path_1.default.join(process.resourcesPath, 'product-sku.json'),
        node_path_1.default.join(process.resourcesPath, 'backend', 'product-sku.json')
    ];
    for (const filePath of candidates) {
        try {
            if (!node_fs_1.default.existsSync(filePath))
                continue;
            const raw = JSON.parse(node_fs_1.default.readFileSync(filePath, 'utf8'));
            const sku = String(raw.sku || '').trim().toLowerCase();
            if (sku === 'personal' || sku === 'enterprise') {
                return sku;
            }
        }
        catch {
            /* ignore */
        }
    }
    return null;
}
function backendEditionEnv() {
    const sku = readPackagedProductSku();
    if (!sku) {
        return {
            XCAGI_GENERIC_EDITION: '1',
            XCAGI_PLATFORM_SHELL: '1',
            XCAGI_DEFAULT_EDITION: 'generic'
        };
    }
    const edition = SKU_RUNTIME_EDITION[sku];
    const env = {
        XCAGI_PRODUCT_SKU: sku,
        XCAGI_PLATFORM_SHELL: sku === 'enterprise' ? '0' : '1',
        XCAGI_DEFAULT_EDITION: edition,
        XCAGI_EDITION: edition
    };
    if (edition === 'minimal') {
        env.XCAGI_MINIMAL_EDITION = '1';
    }
    else if (edition === 'generic') {
        env.XCAGI_GENERIC_EDITION = '1';
    }
    return env;
}
let mainWindow = null;
let backendProcess = null;
let tray = null;
let restartCount = 0;
function repoRoot() {
    return electron_1.app.isPackaged ? process.resourcesPath : node_path_1.default.resolve(__dirname, '..', '..');
}
/** 托盘与窗口图标：与 dist 同级打包的 resources（由 beforePack 生成）。 */
function shellIconPath() {
    const name = process.platform === 'win32' ? 'icon.ico' : 'icon.png';
    return node_path_1.default.join(__dirname, '..', 'resources', name);
}
function backendExecutable() {
    const dataDir = electron_1.app.getPath('userData');
    if (!electron_1.app.isPackaged) {
        const root = repoRoot();
        return {
            command: process.env.PYTHON || 'python',
            args: [
                node_path_1.default.join(root, 'XCAGI', 'run.py'),
                '--desktop',
                '--headless',
                '--host',
                '127.0.0.1',
                '--port',
                String(DEFAULT_PORT),
                '--data-dir',
                dataDir
            ],
            cwd: root
        };
    }
    const backendDir = node_path_1.default.join(process.resourcesPath, 'backend');
    const command = process.platform === 'win32'
        ? node_path_1.default.join(backendDir, 'xcagi-backend.exe')
        : node_path_1.default.join(backendDir, 'xcagi-backend');
    return {
        command,
        args: [
            '--desktop',
            '--headless',
            '--host',
            '127.0.0.1',
            '--port',
            String(DEFAULT_PORT),
            '--data-dir',
            dataDir
        ],
        cwd: node_path_1.default.dirname(command)
    };
}
/** 须确认 uvicorn /api/health，避免 macOS AirPlay 占 5000 时 TCP 误判就绪。 */
async function waitForBackendHealth(port, timeoutMs = 60_000) {
    const started = Date.now();
    while (Date.now() - started <= timeoutMs) {
        try {
            const response = await fetch(`http://127.0.0.1:${port}/api/health`, {
                signal: AbortSignal.timeout(3_000)
            });
            const server = (response.headers.get('server') || '').toLowerCase();
            if (response.ok && server.includes('uvicorn')) {
                startupMarks.tcp5000Ms = Date.now() - (startupMarks.backendSpawnMs ?? started);
                return;
            }
            if (server.includes('airtunes')) {
                console.warn(`[xcagi-desktop] 端口 ${port} 被 macOS 隔空播放占用，等待 XCAGI 后端…`);
            }
        }
        catch {
            /* backend still booting */
        }
        await new Promise(resolve => setTimeout(resolve, 500));
    }
    const airplayHint = process.platform === 'darwin' && port === 5000
        ? ' macOS「隔空播放接收器」占用 5000，请在系统设置中关闭，或设置 XCAGI_DESKTOP_PORT=17500。'
        : '';
    throw new Error(`后端 /api/health 在 ${timeoutMs}ms 内未就绪（端口 ${port}）。${airplayHint}`);
}
const startupMarks = {};
function readPackagedAppVersion() {
    if (!electron_1.app.isPackaged)
        return 'dev';
    const candidates = [
        node_path_1.default.join(process.resourcesPath, 'backend', 'version.txt'),
        node_path_1.default.join(process.resourcesPath, 'product-sku.json')
    ];
    for (const filePath of candidates) {
        try {
            if (!node_fs_1.default.existsSync(filePath))
                continue;
            const raw = node_fs_1.default.readFileSync(filePath, 'utf8').trim();
            if (filePath.endsWith('version.txt'))
                return raw || 'unknown';
            const json = JSON.parse(raw);
            return `${json.sku || 'enterprise'}-${json.schema_version ?? 1}`;
        }
        catch {
            /* ignore */
        }
    }
    return electron_1.app.getVersion();
}
/** 前端 hash 变更时须清 Electron 缓存，避免旧 index-*.js 引用已不存在的 chunk。 */
function readFrontendCacheKey() {
    const base = readPackagedAppVersion();
    const indexCandidates = [
        node_path_1.default.join(process.resourcesPath, 'backend', '_internal', 'templates', 'vue-dist', 'index.html'),
        node_path_1.default.join(process.resourcesPath, 'frontend', 'index.html')
    ];
    for (const indexPath of indexCandidates) {
        try {
            if (!node_fs_1.default.existsSync(indexPath))
                continue;
            const html = node_fs_1.default.readFileSync(indexPath, 'utf8');
            const match = html.match(/\/assets\/js\/index-([A-Za-z0-9_-]+)\.js/);
            if (match?.[1]) {
                return `${base}@${match[1]}`;
            }
        }
        catch {
            /* ignore */
        }
    }
    return base;
}
function shouldClearFrontendCache() {
    const marker = node_path_1.default.join(electron_1.app.getPath('userData'), 'frontend-cache-version.txt');
    const current = readFrontendCacheKey();
    try {
        const prev = node_fs_1.default.readFileSync(marker, 'utf8').trim();
        return prev !== current;
    }
    catch {
        return true;
    }
}
function markFrontendCacheCleared() {
    const marker = node_path_1.default.join(electron_1.app.getPath('userData'), 'frontend-cache-version.txt');
    node_fs_1.default.writeFileSync(marker, readFrontendCacheKey(), 'utf8');
}
/** 分阶段就绪：TCP 后即可出窗；desktop/status 软等待，不阻塞 60s 全量 Mod。 */
async function waitForBackendStatus(port, timeoutMs = 15_000) {
    const started = Date.now();
    while (Date.now() - started <= timeoutMs) {
        try {
            const response = await fetch(`http://127.0.0.1:${port}/api/desktop/status`);
            if (response.ok) {
                startupMarks.desktopStatusMs = Date.now() - (startupMarks.backendSpawnMs ?? started);
                return true;
            }
        }
        catch {
            /* backend still importing routers */
        }
        await new Promise(resolve => setTimeout(resolve, 400));
    }
    console.warn(`[xcagi-desktop] /api/desktop/status 未在 ${timeoutMs}ms 内就绪，仍加载前端`);
    return false;
}
function startBackend() {
    if (backendProcess) {
        return;
    }
    const executable = backendExecutable();
    if (electron_1.app.isPackaged && !node_fs_1.default.existsSync(executable.command)) {
        void electron_1.dialog.showErrorBox(APP_NAME, `找不到后端程序：${executable.command}`);
        return;
    }
    startupMarks.backendSpawnMs = Date.now();
    backendProcess = (0, node_child_process_1.spawn)(executable.command, executable.args, {
        cwd: executable.cwd,
        env: {
            ...process.env,
            XCAGI_DESKTOP_MODE: '1',
            XCAGI_DATA_DIR: electron_1.app.getPath('userData'),
            XCAGI_UVICORN_RELOAD: '0',
            ...backendEditionEnv(),
            PYTHONUTF8: '1'
        },
        windowsHide: true
    });
    backendProcess.stdout.on('data', data => process.stdout.write(`[xcagi-backend] ${data}`));
    backendProcess.stderr.on('data', data => process.stderr.write(`[xcagi-backend] ${data}`));
    backendProcess.on('exit', code => {
        backendProcess = null;
        if (electron_1.app.isQuitting) {
            return;
        }
        restartCount += 1;
        if (restartCount <= 3) {
            setTimeout(startBackend, 1500);
            return;
        }
        void electron_1.dialog.showErrorBox(APP_NAME, `后端服务已退出（code=${code}），请重启 XCAGI。`);
    });
}
function runBackendMigration() {
    const executable = backendExecutable();
    return new Promise((resolve, reject) => {
        const child = (0, node_child_process_1.spawn)(executable.command, [...executable.args, '--migrate-only', '--backup'], {
            cwd: executable.cwd,
            env: {
                ...process.env,
                XCAGI_DESKTOP_MODE: '1',
                XCAGI_DATA_DIR: electron_1.app.getPath('userData'),
                XCAGI_GENERIC_EDITION: '1',
                XCAGI_PLATFORM_SHELL: '1',
                PYTHONUTF8: '1'
            },
            windowsHide: true
        });
        let stderr = '';
        child.stderr.on('data', data => {
            stderr += String(data);
            process.stderr.write(`[xcagi-migrate] ${data}`);
        });
        child.stdout.on('data', data => process.stdout.write(`[xcagi-migrate] ${data}`));
        child.on('error', reject);
        child.on('exit', code => {
            if (code === 0) {
                resolve();
            }
            else {
                reject(new Error(`数据库迁移失败（code=${code}）: ${stderr}`));
            }
        });
    });
}
async function exportSupportBundleInteractive() {
    try {
        const res = await fetch(`http://127.0.0.1:${DEFAULT_PORT}/api/desktop/support-bundle`);
        if (!res.ok) {
            void electron_1.dialog.showErrorBox(APP_NAME, `导出失败：HTTP ${res.status}`);
            return;
        }
        const buf = Buffer.from(await res.arrayBuffer());
        const iso = new Date().toISOString().replace(/[:.]/g, '-');
        const defaultPath = node_path_1.default.join(electron_1.app.getPath('downloads'), `xcagi-support-${iso}.zip`);
        const win = electron_1.BrowserWindow.getFocusedWindow() ?? mainWindow;
        const saveOpts = {
            title: '导出诊断包',
            defaultPath,
            filters: [{ name: 'ZIP', extensions: ['zip'] }]
        };
        const { canceled, filePath } = win
            ? await electron_1.dialog.showSaveDialog(win, saveOpts)
            : await electron_1.dialog.showSaveDialog(saveOpts);
        if (canceled || !filePath) {
            return;
        }
        await node_fs_1.default.promises.writeFile(filePath, buf);
        const parent = win ?? mainWindow;
        const saved = {
            type: 'info',
            title: APP_NAME,
            message: '诊断包已保存',
            detail: filePath
        };
        if (parent) {
            void electron_1.dialog.showMessageBox(parent, saved);
        }
        else {
            void electron_1.dialog.showMessageBox(saved);
        }
    }
    catch (error) {
        void electron_1.dialog.showErrorBox(APP_NAME, error instanceof Error ? error.message : String(error));
    }
}
/** macOS 全屏/恢复后窗口可能只剩顶部一条，拉回工作区。 */
function ensureMacWindowInWorkArea(win) {
    if (process.platform !== 'darwin')
        return;
    const bounds = win.getBounds();
    const work = electron_1.screen.getDisplayMatching(bounds).workArea;
    const minW = 1180;
    const minH = 760;
    let { x, y, width, height } = bounds;
    if (width < minW)
        width = Math.min(minW, work.width);
    if (height < minH)
        height = Math.min(minH, work.height);
    if (y < work.y || height < minH) {
        y = work.y + 8;
        height = Math.min(Math.max(height, minH), work.height - 16);
    }
    if (x + width > work.x + work.width) {
        x = work.x + Math.max(0, work.width - width);
    }
    if (x < work.x)
        x = work.x;
    if (width !== bounds.width || height !== bounds.height || x !== bounds.x || y !== bounds.y) {
        win.setBounds({ x, y, width, height });
    }
}
function tagDesktopWebContents(win) {
    const classes = ['xcagi-electron'];
    if (process.platform === 'darwin')
        classes.push('xcagi-electron-mac');
    if (process.platform === 'win32')
        classes.push('xcagi-electron-win');
    void win.webContents
        .executeJavaScript(classes.map(c => `document.documentElement.classList.add('${c}');`).join(''))
        .catch(() => { });
}
function stopBackend() {
    const child = backendProcess;
    backendProcess = null;
    if (!child || child.killed) {
        return;
    }
    child.kill(process.platform === 'win32' ? undefined : 'SIGTERM');
}
async function createWindow() {
    const icon = shellIconPath();
    const winOpts = {
        width: 1440,
        height: 920,
        minWidth: 1180,
        minHeight: 760,
        title: APP_NAME,
        webPreferences: {
            preload: node_path_1.default.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true
        }
    };
    if (node_fs_1.default.existsSync(icon)) {
        winOpts.icon = icon;
    }
    if (process.platform === 'darwin') {
        winOpts.frame = true;
        winOpts.titleBarStyle = 'default';
    }
    winOpts.show = false;
    winOpts.backgroundColor = '#f4f7fb';
    mainWindow = new electron_1.BrowserWindow(winOpts);
    mainWindow.on('closed', () => {
        mainWindow = null;
    });
    if (process.platform === 'darwin') {
        mainWindow.on('leave-full-screen', () => {
            if (mainWindow)
                ensureMacWindowInWorkArea(mainWindow);
        });
        mainWindow.on('restore', () => {
            if (mainWindow)
                ensureMacWindowInWorkArea(mainWindow);
        });
    }
    await waitForBackendHealth(DEFAULT_PORT);
    if (shouldClearFrontendCache()) {
        try {
            await mainWindow.webContents.session.clearCache();
            markFrontendCacheCleared();
        }
        catch {
            /* ignore */
        }
    }
    mainWindow.webContents.on('did-finish-load', () => {
        if (mainWindow)
            tagDesktopWebContents(mainWindow);
    });
    await mainWindow.loadURL(desktopInitialUrl(), {
        extraHeaders: 'Cache-Control: no-cache\r\n'
    });
    tagDesktopWebContents(mainWindow);
    if (process.platform === 'darwin') {
        ensureMacWindowInWorkArea(mainWindow);
    }
    mainWindow.show();
    mainWindow.focus();
    void waitForBackendStatus(DEFAULT_PORT).then(ok => {
        console.info('[xcagi-desktop] startup', JSON.stringify({
            ...startupMarks,
            desktopStatusOk: ok
        }));
    });
    (0, updater_1.configureUpdater)(mainWindow, runBackendMigration);
}
function createMenu() {
    const appSubmenu = [
        { label: '打开数据目录', click: () => void electron_1.shell.openPath(electron_1.app.getPath('userData')) },
        {
            label: '导出诊断包…',
            click: () => void exportSupportBundleInteractive()
        },
        { label: '检查更新', click: () => void (0, updater_1.checkForUpdates)() },
        { type: 'separator' },
        { role: 'quit', label: '退出' }
    ];
    if (process.platform === 'darwin') {
        appSubmenu.unshift({ role: 'about', label: `关于 ${APP_NAME}` }, { type: 'separator' }, { role: 'services' }, { type: 'separator' }, { role: 'hide', label: `隐藏 ${APP_NAME}` }, { role: 'hideOthers' }, { role: 'unhide' }, { type: 'separator' });
    }
    const template = [
        {
            label: APP_NAME,
            submenu: appSubmenu
        },
        { role: 'editMenu', label: '编辑' },
        { role: 'viewMenu', label: '视图' },
        { role: 'windowMenu', label: '窗口' }
    ];
    if (process.platform === 'darwin') {
        template.push({ role: 'help', label: '帮助' });
    }
    electron_1.Menu.setApplicationMenu(electron_1.Menu.buildFromTemplate(template));
}
function menuBarTrayIcon() {
    const iconPath = shellIconPath();
    if (!node_fs_1.default.existsSync(iconPath)) {
        return null;
    }
    const image = electron_1.nativeImage.createFromPath(iconPath);
    if (image.isEmpty()) {
        return null;
    }
    // Windows 托盘须小图标；macOS 菜单栏禁止用大图（会撑满系统顶栏）
    const edge = process.platform === 'win32' ? 16 : 18;
    const resized = image.resize({ width: edge, height: edge, quality: 'best' });
    if (process.platform === 'darwin') {
        resized.setTemplateImage(true);
    }
    return resized;
}
function createTray() {
    // macOS：与 Cursor 等原生应用一致，不占系统菜单栏右侧；仅 Dock + 左上角「XCAGI」文字菜单
    if (process.platform === 'darwin') {
        return;
    }
    const image = menuBarTrayIcon();
    if (!image) {
        return;
    }
    tray = new electron_1.Tray(image);
    tray.setToolTip(APP_NAME);
    tray.setContextMenu(electron_1.Menu.buildFromTemplate([
        { label: '显示 XCAGI', click: () => mainWindow?.show() },
        { label: '打开数据目录', click: () => void electron_1.shell.openPath(electron_1.app.getPath('userData')) },
        { type: 'separator' },
        { label: '退出', click: () => electron_1.app.quit() }
    ]));
}
const gotLock = electron_1.app.requestSingleInstanceLock();
if (!gotLock) {
    electron_1.app.quit();
}
else {
    electron_1.app.on('second-instance', () => {
        if (mainWindow) {
            if (mainWindow.isMinimized())
                mainWindow.restore();
            mainWindow.focus();
        }
    });
    electron_1.app.on('before-quit', () => {
        electron_1.app.isQuitting = true;
        stopBackend();
    });
    electron_1.app.whenReady().then(async () => {
        const sku = readPackagedProductSku();
        if (sku && !process.env.XCAGI_UPDATE_URL) {
            process.env.XCAGI_UPDATE_URL = SKU_UPDATE_URL[sku];
        }
        function getLanIPv4() {
            const nets = (0, node_os_1.networkInterfaces)();
            for (const name of Object.keys(nets)) {
                for (const iface of nets[name] || []) {
                    if (iface.family === 'IPv4' && !iface.internal) {
                        return iface.address;
                    }
                }
            }
            return '127.0.0.1';
        }
        electron_1.ipcMain.handle('xcagi:pairing-qr', async () => {
            const host = getLanIPv4();
            const port = DEFAULT_PORT;
            const nonce = node_crypto_1.default.randomBytes(12).toString('base64url');
            const exp = Math.floor(Date.now() / 1000) + 300;
            try {
                const res = await fetch(`http://127.0.0.1:${port}/api/mobile/v1/pairing/issue`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ host, port })
                });
                if (res.ok) {
                    const json = (await res.json());
                    if (json?.data?.nonce) {
                        return JSON.stringify(json.data);
                    }
                }
            }
            catch {
                /* backend offline — return local payload */
            }
            return JSON.stringify({ host, port, nonce, exp });
        });
        electron_1.ipcMain.handle('xcagi:get-data-dir', () => electron_1.app.getPath('userData'));
        electron_1.ipcMain.handle('xcagi:export-support-bundle', () => exportSupportBundleInteractive());
        electron_1.ipcMain.handle('xcagi:check-for-updates', () => (0, updater_1.checkForUpdates)());
        electron_1.ipcMain.handle('xcagi:install-update', () => (0, updater_1.installUpdate)(runBackendMigration));
        createMenu();
        createTray();
        startBackend();
        try {
            await createWindow();
        }
        catch (error) {
            void electron_1.dialog.showErrorBox(APP_NAME, error instanceof Error ? error.message : String(error));
            electron_1.app.quit();
        }
    });
    electron_1.app.on('activate', () => {
        if (electron_1.BrowserWindow.getAllWindows().length === 0) {
            void createWindow();
        }
    });
}
