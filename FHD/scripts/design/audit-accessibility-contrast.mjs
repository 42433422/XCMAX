// Static WCAG 2.2 contrast audit for explicitly paired source colors.
// Not a rendered-page audit: only registered pairs, including explicit
// single-layer alpha backgrounds, are checked. Unresolved pairs fail closed.
import { readFileSync } from 'node:fs';

const root = new URL('../../', import.meta.url);
const tokens = JSON.parse(readFileSync(new URL('config/mobile_design_tokens.json', root), 'utf8'));
const dialog = readFileSync(new URL('frontend/src/components/ConfirmDialog.vue', root), 'utf8');
const generatedCss = readFileSync(new URL('frontend/src/styles/design-tokens.generated.css', root), 'utf8');
const marketDialog = readFileSync(new URL('../成都修茈科技有限公司/MODstore_deploy/market/src/components/AppConfirmDialog.vue', root), 'utf8');
const marketGeneratedCss = readFileSync(new URL('../成都修茈科技有限公司/MODstore_deploy/market/src/design-tokens.generated.css', root), 'utf8');
for (const fragment of ['<ElDialog', 'data-dialog-initial-focus', ':close-on-press-escape="true"', '@opened="focusCancel"']) {
  if (!marketDialog.includes(fragment)) throw Error('Market modal focus contract missing: ' + fragment);
}
const themeSource = readFileSync(new URL('mobile-flutter-poc/lib/src/theme/app_theme.dart', root), 'utf8');
for (const [fragment, expected] of [
  ['static const brand = DesignTokens.semanticLightPrimary;', 1],
  ['static const textTertiary = DesignTokens.colorsNeutralLightN500;', 1],
  ['onPrimary: surface,', 1],
  ['onPrimary: DesignTokens.colorsNeutralLightN900,', 1],
  ['onSecondary: DesignTokens.colorsNeutralLightN900,', 2],
  ['onError: DesignTokens.colorsNeutralLightN900,', 2],
]) {
  if (themeSource.split(fragment).length - 1 !== expected)
    throw Error('Theme contract mismatch: ' + fragment);
}

function resolveColor(value, seen = [], sheet = generatedCss, backdrop) {
  if (value === 'white') return '#FFFFFF';
  if (/^#[0-9a-f]{6}$/i.test(value)) return value;
  const rgba = /^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d*\.?\d+)\s*\)$/i.exec(value ?? '');
  if (rgba) {
    if (!/^#[0-9a-f]{6}$/i.test(backdrop ?? '')) throw Error('Alpha background requires explicit opaque backdrop: ' + value);
    const channels = rgba.slice(1, 4).map(Number), alpha = Number(rgba[4]);
    if (channels.some(channel => channel > 255) || alpha > 1) throw Error('Invalid rgba color: ' + value);
    const base = backdrop.slice(1).match(/../g).map(channel => parseInt(channel, 16));
    return '#' + channels.map((channel, i) => Math.round(channel * alpha + base[i] * (1 - alpha)).toString(16).padStart(2, '0')).join('');
  }
  const reference = /^var\(\s*(--[a-z0-9-]+)\s*(?:,\s*(#[0-9a-f]{6}))?\s*\)$/i.exec(value ?? '');
  if (!reference) throw Error('Unsupported color expression: ' + value);
  const key = reference[1];
  if (seen.includes(key)) throw Error('Cyclic CSS reference: ' + key);
  // Never treat a fallback as proof of the actual generated token value.
  const declaration = sheet.split('\n').find(line => line.trim().startsWith(key + ':'));
  if (!declaration) throw Error('Missing generated CSS token: ' + key);
  const raw = declaration.slice(declaration.indexOf(':') + 1).replace(/;\s*$/, '').trim();
  return resolveColor(raw, [...seen, key], sheet, backdrop);
}


function token(path, ancestors = []) {
  if (ancestors.includes(path)) throw Error('Cyclic token: ' + path);
  const value = path.split('.').reduce((obj, key) => obj?.[key], tokens);
  if (typeof value !== 'string') throw Error('Missing token: ' + path);
  const reference = /^\{([^}]+)\}$/.exec(value);
  return reference ? token(reference[1], [...ancestors, path]) : value;
}

function luminance(color) {
  if (color === 'white') color = '#FFFFFF';
  if (!/^#[0-9a-f]{6}$/i.test(color)) throw Error('Unsupported opaque color: ' + color);
  const [r, g, b] = color.slice(1).match(/../g).map((v) => {
    const s = parseInt(v, 16) / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a, b) {
  const x = luminance(a), y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

if (Math.abs(contrast('#000000', '#FFFFFF') - 21) > 1e-9 ||
    contrast('#FFFFFF', '#FFFFFF') !== 1) {
  throw Error('Contrast formula self-test failed');
}

const rows = [];
const mobile = 'platform_overrides.mobile.colors.';
const lightSurface = tokens.semantic?.light?.surface ? 'semantic.light.surface' : 'colors.neutral_light.n00';
const lightPrimary = tokens.semantic?.light?.primary ? 'semantic.light.primary' : 'colors.brand.primary';
function pair(label, fg, bg, minimum = 4.5) {
  try {
    const foreground = resolveColor(fg()), background = resolveColor(bg());
    const ratio = contrast(foreground, background);
    rows.push({ label, foreground, background, ratio: Number(ratio.toFixed(4)), minimum,
      result: ratio >= minimum ? 'PASS_STATIC_PAIR' : 'FAIL_STATIC_PAIR' });
  } catch (error) {
    rows.push({ label, minimum, result: 'UNRESOLVED', error: String(error) });
  }
}
function t(label, fg, bg) {
  pair(label, () => token(fg), () => token(bg));
}

for (const mode of ['light', 'dark']) {
  t('Shared ' + mode + ' main text / surface', 'semantic.' + mode + '.text_primary', 'semantic.' + mode + '.surface');
  t('Shared ' + mode + ' secondary text / surface', 'semantic.' + mode + '.text_secondary', 'semantic.' + mode + '.surface');
}

t('Flutter light onPrimary', lightSurface, lightPrimary);
t('Flutter light onSecondary', 'colors.neutral_light.n900', 'colors.status.success');
t('Flutter light onError', 'colors.neutral_light.n900', 'colors.status.danger');
t('Flutter light tertiary text on surface', 'colors.neutral_light.n500', lightSurface);
t('Flutter light tertiary text on elevated surface', 'colors.neutral_light.n500', 'colors.neutral_light.n100');
t('Flutter dark tertiary text on high surface', mobile + 'dark_text_tertiary', mobile + 'dark_surface_high');
t('Flutter dark onPrimary', 'colors.neutral_light.n900', 'colors.brand.primary_light');
t('Flutter dark onSecondary', 'colors.neutral_light.n900', 'colors.status.success');
t('Flutter dark onError', 'colors.neutral_light.n900', 'colors.status.danger');
t('Flutter light user bubble', lightSurface, lightPrimary);
t('Flutter dark user bubble', 'colors.chat.user_text_dark', 'colors.brand.primary_dark');
t('Flutter light approval status', mobile + 'light_on_brand_container', 'colors.brand.primary_container');
t('Flutter dark approval status', mobile + 'dark_on_brand_container', mobile + 'dark_brand_container');

for (const name of ['primary', 'secondary', 'danger', 'success']) {
  for (const state of ['', ':hover']) {
    const normal = new RegExp('\\.btn-' + name + '\\s*\\{([^}]+)\\}').exec(dialog)?.[1];
    const block = state
      ? new RegExp('\\.btn-' + name + ':hover\\s*\\{([^}]+)\\}').exec(dialog)?.[1]
      : normal;
    function cssValue(source, prop) {
      return new RegExp('(?:^|;)\\s*' + prop + '\\s*:\\s*([^;]+)').exec(source ?? '')?.[1]?.trim();
    }
    pair('Desktop ConfirmDialog ' + name + (state || ':default'),
      () => cssValue(block, 'color') ?? cssValue(normal, 'color'),
      () => cssValue(block, 'background-color') ?? cssValue(normal, 'background-color'));
  }
}

function marketBlock(selector) {
  const start = marketDialog.indexOf(selector + ' {');
  if (start < 0) throw Error('Market selector missing: ' + selector);
  const end = marketDialog.indexOf('}', start);
  if (end < 0) throw Error('Market block unterminated: ' + selector);
  return marketDialog.slice(start + selector.length + 2, end);
}
function marketDeclaration(block, key) {
  const value = new RegExp('(?:^|;)\\s*' + key + '\\s*:\\s*([^;]+)').exec(block)?.[1]?.trim();
  if (!value) throw Error('Market style missing: ' + key);
  return resolveColor(value, [], marketGeneratedCss);
}
for (const [label, selector] of [
  ['primary', '.app-confirm-dialog__confirm:not(.app-confirm-dialog__confirm--danger)'],
  ['danger', '.app-confirm-dialog__confirm--danger'],
]) {
  pair('Market AppConfirmDialog ' + label,
    () => marketDeclaration(marketBlock(selector), 'color'),
    () => marketDeclaration(marketBlock(selector), 'background'));
}
// Audit the component's actual focus declaration and the registered Element
// Plus dialog overlay surface, not a detached copy of the expected colors.
const marketThemeCss = readFileSync(new URL('../成都修茈科技有限公司/MODstore_deploy/market/src/tokens.css', root), 'utf8');
if (!marketThemeCss.includes('--el-bg-color-overlay: var(--wb-dialog-bg);')) {
  throw Error('Market dialog overlay surface alias changed');
}
const marketFocusBlock = marketBlock('.app-confirm-dialog__cancel:focus-visible,\n.app-confirm-dialog__confirm:focus-visible');
const marketFocusColor = /(?:^|;)\s*outline\s*:\s*[\d.]+px\s+solid\s+([^;]+);/.exec(marketFocusBlock)?.[1]?.trim();
for (const label of ['light', 'dark']) {
  const surfaceCssVariable = '--xc-token-market-' + label + '-wb-dialog-bg';
  if (!marketThemeCss.includes('--wb-dialog-bg: var(' + surfaceCssVariable + ');')) {
    throw Error('Market dialog surface alias missing: ' + label);
  }
  pair('Market AppConfirmDialog focus ring on ' + label,
    () => resolveColor(marketFocusColor, [], marketGeneratedCss),
    () => resolveColor('var(' + surfaceCssVariable + ')', [], marketGeneratedCss), 3);
}

// Market light muted text is rendered in blockquotes, placeholders, sidebar
// and dialog text. Keep these semantic roles readable on registered surfaces.
for (const [role, backgrounds] of [
  ['wb-text-muted', ['color-bg-body', 'color-bg-page', 'color-bg-card']],
  ['wb-sidebar-text-muted', ['color-bg-body', 'color-bg-page']],
  ['wb-dialog-text-muted', ['wb-dialog-bg']],
]) {
  for (const background of backgrounds) {
    pair('Market light ' + role + ' / ' + background,
      () => resolveColor('var(--xc-token-market-light-' + role + ')', [], marketGeneratedCss),
      () => resolveColor('var(--xc-token-market-light-' + background + ')', [], marketGeneratedCss));
  }
}

// Market dark muted ordinary text is consumed by Element Plus placeholders
// and legacy workbench aliases. Cover the registered opaque surfaces;
// alpha-composited / overlay states still require rendered inspection.
for (const [role, backgrounds] of [
  ['wb-text-muted', ['color-bg-page', 'color-bg-card', 'wb-surface-elevated', 'wb-input-bg']],
  ['wb-sidebar-text-muted', ['wb-sidebar-bg', 'wb-sidebar-item-active']],
  ['wb-dialog-text-muted', ['wb-dialog-bg']],
]) {
  for (const background of backgrounds) {
    pair('Market dark ' + role + ' / ' + background,
      () => resolveColor('var(--xc-token-market-dark-' + role + ')', [], marketGeneratedCss),
      () => resolveColor('var(--xc-token-market-dark-' + background + ')', [], marketGeneratedCss));
  }
}
pair('Market dark wb-text-muted / body',
  () => resolveColor('var(--xc-token-market-dark-wb-text-muted)', [], marketGeneratedCss),
  () => resolveColor('var(--xc-token-market-base-color-bg-body)', [], marketGeneratedCss));

// The global office primary button is separate from ConfirmDialog. Check
// both endpoints of its two-stop gradient; rendered/cascade checks remain
// mandatory. Reject unregistered expressions rather than trusting fallbacks.
const officeButtonCss = readFileSync(new URL('frontend/src/styles/css/office-theme.css', root), 'utf8');
function officePrimaryRule(state) {
  return new RegExp('^\\.btn-primary' + state + '\\s*\\{([^}]+)\\}', 'm').exec(officeButtonCss)?.[1];
}
function officePrimaryDeclaration(block, property) {
  return new RegExp('(?:^|;)\\s*' + property + '\\s*:\\s*([^;]+)').exec(block ?? '')?.[1]?.trim();
}
const officePrimaryDefault = officePrimaryRule('');
for (const state of ['', ':hover']) {
  const block = officePrimaryRule(state);
  const foreground = officePrimaryDeclaration(block, 'color') ?? officePrimaryDeclaration(officePrimaryDefault, 'color');
  const background = officePrimaryDeclaration(block, 'background');
  const stops = /^linear-gradient\(\s*[^,]+,\s*(var\(--[\w-]+\))\s+0%,\s*(var\(--[\w-]+\))\s+100%\s*\)$/.exec(background ?? '');
  for (const index of [1, 2]) {
    pair('Desktop office primary ' + (state || ':default') + ' gradient stop ' + index,
      () => foreground, () => stops?.[index]);
  }
}

// Office success uses registered foreground/background in both states.
// Hover changes elevation, not text contrast.
const officeSuccessDefault = /^\.btn-success\s*\{([^}]+)\}/m.exec(officeButtonCss)?.[1];
const officeSuccessHover = /^\.btn-success:hover\s*\{([^}]+)\}/m.exec(officeButtonCss)?.[1];
for (const [state, block] of [['default', officeSuccessDefault], ['hover', officeSuccessHover]]) {
  if (!block) throw Error('Missing office success state: ' + state);
  const fg = officePrimaryDeclaration(block, 'color') ?? officePrimaryDeclaration(officeSuccessDefault, 'color');
  const bg = officePrimaryDeclaration(block, 'background') ?? officePrimaryDeclaration(officeSuccessDefault, 'background');
  if (!fg?.startsWith('var(--xc-token-') || !bg?.startsWith('var(--xc-token-'))
    throw Error('Office success colors must use generated tokens');
  pair('Desktop office success ' + state, () => fg, () => bg);
}


// Read the order-list component's actual ordinary-text and opaque surface
// declarations. Keep the existing explicit light override paired with its
// own background; default rules must remain readable even without a theme attribute.
const marketOrders = readFileSync(new URL('../成都修茈科技有限公司/MODstore_deploy/market/src/views/OrderListView.vue', root), 'utf8');
function orderStyle(selector) {
  const marker = '\n' + selector + ' {';
  const start = marketOrders.indexOf(marker);
  if (start < 0) throw Error('Missing order-list selector: ' + selector);
  const end = marketOrders.indexOf('}', start);
  if (end < 0) throw Error('Unterminated order-list selector: ' + selector);
  return marketOrders.slice(start + marker.length, end);
}
for (const mode of ['dark', 'light']) {
  const prefix = mode === 'light' ? "html[data-workbench-theme='light'] " : '';
  for (const [selector, surface] of [
    ['.order-list-toolbar__hint', '.order-list-page'],
    ['.loading', '.order-list-page'],
    ['.order-no', '.order-card'],
    ['.order-time', '.order-card'],
    ['.empty', '.order-list-page'],
  ]) {
    pair('Market order list ' + mode + ' ' + selector,
      () => {
        const value = /(?:^|;)\s*color\s*:\s*([^;]+);/.exec(orderStyle(prefix + selector))?.[1]?.trim();
        if (!value?.startsWith('var(--xc-token-')) throw Error('Order-list text must use a generated token: ' + selector);
        return resolveColor(value, [], marketGeneratedCss);
      },
      () => marketDeclaration(orderStyle(prefix + surface), 'background'));
  }
}

// The active filter and light status badges have translucent backgrounds.
// Composite against the component's explicit page/card surface, not white by assumption.
function orderTokenColor(selector, property, backdrop) {
  const value = new RegExp('(?:^|;)\\s*' + property + '\\s*:\\s*([^;]+);').exec(orderStyle(selector))?.[1]?.trim();
  if (!value?.startsWith('var(--xc-token-')) throw Error('Order-list style must use a generated token: ' + selector + ' ' + property);
  return resolveColor(value, [], marketGeneratedCss, backdrop);
}
const orderLight = "html[data-workbench-theme='light'] ";
pair('Market order list light active filter',
  () => orderTokenColor(orderLight + '.filter-btn.active', 'color'),
  () => orderTokenColor(orderLight + '.filter-btn.active', 'background',
    marketDeclaration(orderStyle(orderLight + '.order-list-page'), 'background')));
for (const status of ['paid', 'pending']) {
  pair('Market order list light badge ' + status,
    () => orderTokenColor(orderLight + '.order-status.' + status, 'color'),
    () => orderTokenColor(orderLight + '.order-status.' + status, 'background',
      marketDeclaration(orderStyle(orderLight + '.order-card'), 'background')));
  pair('Market order list dark badge ' + status,
    () => orderTokenColor('.order-status.' + status, 'color'),
    () => marketDeclaration(orderStyle('.order-status'), 'background'));
}
// Keyboard focus must remain distinguishable on both theme surfaces.
const orderFocusSelector = '.order-card:focus-visible, .retry-btn:focus-visible';
const orderLightFocusSelector = orderLight + '.order-card:focus-visible,\n' + orderLight + '.retry-btn:focus-visible';
const orderFocusValue = /(?:^|;)\s*outline\s*:\s*[\d.]+px\s+solid\s+([^;]+);/.exec(orderStyle(orderFocusSelector))?.[1]?.trim();
for (const mode of ['dark', 'light']) {
  const prefix = mode === 'light' ? orderLight : '';
  for (const surface of ['.order-list-page', '.order-card']) {
    pair('Market order list ' + mode + ' focus / ' + surface,
      () => {
        if (mode === 'light') return orderTokenColor(orderLightFocusSelector, 'outline-color');
        if (!orderFocusValue?.startsWith('var(--xc-token-')) throw Error('Order-list focus must use a generated token');
        return resolveColor(orderFocusValue, [], marketGeneratedCss);
      },
      () => marketDeclaration(orderStyle(prefix + surface), 'background'), 3);
  }
}
console.log(JSON.stringify({ scope: 'static source pairs only (explicit alpha backgrounds included)', rows }, null, 2));
if (rows.some((row) => row.result !== 'PASS_STATIC_PAIR')) process.exitCode = 1;
