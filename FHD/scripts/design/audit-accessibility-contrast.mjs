// Static WCAG 2.2 contrast audit for explicitly paired, opaque source colors.
// Not a rendered-page audit: gradients, alpha blending and component states
// require browser/device measurements. Unresolved pairs fail closed.
import { readFileSync } from 'node:fs';

const root = new URL('../../', import.meta.url);
const tokens = JSON.parse(readFileSync(new URL('config/mobile_design_tokens.json', root), 'utf8'));
const dialog = readFileSync(new URL('frontend/src/components/ConfirmDialog.vue', root), 'utf8');
const generatedCss = readFileSync(new URL('frontend/src/styles/design-tokens.generated.css', root), 'utf8');

function resolveColor(value, seen = []) {
  if (value === 'white') return '#FFFFFF';
  if (/^#[0-9a-f]{6}$/i.test(value)) return value;
  const reference = /^var\(\s*(--[a-z0-9-]+)\s*(?:,\s*(#[0-9a-f]{6}))?\s*\)$/i.exec(value ?? '');
  if (!reference) throw Error('Unsupported color expression: ' + value);
  const key = reference[1];
  if (seen.includes(key)) throw Error('Cyclic CSS reference: ' + key);
  // Never treat a fallback as proof of the actual generated token value.
  const declaration = generatedCss.split('\n').find(line => line.trim().startsWith(key + ':'));
  if (!declaration) throw Error('Missing generated CSS token: ' + key);
  const raw = declaration.slice(declaration.indexOf(':') + 1).replace(/;\s*$/, '').trim();
  return resolveColor(raw, [...seen, key]);
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

t('Flutter light onPrimary', lightSurface, lightPrimary);
t('Flutter light onSecondary', lightSurface, 'colors.status.success');
t('Flutter light onError', lightSurface, 'colors.status.danger');
t('Flutter light tertiary text on surface', 'colors.neutral_light.n400', lightSurface);
t('Flutter dark tertiary text on high surface', mobile + 'dark_text_tertiary', mobile + 'dark_surface_high');
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
console.log(JSON.stringify({ scope: 'static opaque source pairs only', rows }, null, 2));
if (rows.some((row) => row.result !== 'PASS_STATIC_PAIR')) process.exitCode = 1;
