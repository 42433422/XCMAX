// Dependency-free design token generator. Run from any directory.
import { readFileSync, writeFileSync } from 'node:fs';
function render(c) {
 const keb=s=>s.replace(/[._]/g,"-"),camel=s=>s.split(/[._-]/).map((x,i)=>i?x[0].toUpperCase()+x.slice(1):x).join("");
 const ref=/^\{([a-z0-9_.-]+)\}$/;
 const groups=["colors","spacing","radius","elevation","typography","motion","font_weights","focus","semantic","components"];
 function lookup(p,seen=[]){if(seen.includes(p))throw Error("Cyclic token "+p);let v=c;for(const k of p.split(".")){if(!v||!Object.hasOwn(v,k))throw Error("Unknown token "+p);v=v[k];}let m=typeof v==="string"&&ref.exec(v);return m?lookup(m[1],[...seen,p]):v;}
 function flatten(o,p){if(!o||typeof o!=="object")throw Error("Missing group "+p);return Object.entries(o).flatMap(([k,v])=>v&&typeof v==="object"?flatten(v,p+"."+k):[[p+"."+k,v]]);}
 function css(p,v){const resolved=lookup(p);if(typeof v==="string"&&ref.test(v)){const target=ref.exec(v)[1];if(groups.includes(target.split(".")[0]))return `var(--xc-token-${keb(target)})`;const marketPrefix="platform_overrides.market.profiles.";if(p.startsWith(marketPrefix)&&target.startsWith(marketPrefix)){const [profile,key]=target.slice(marketPrefix.length).split(".");return `var(--xc-token-market-${keb(profile)}-${key})`;}throw Error("Non-shared reference "+p);}if(typeof resolved==="string"){if(p.endsWith(".weight")){if(!c.font_weights[resolved])throw Error("Invalid weight "+p);return String(c.font_weights[resolved]);}if(/[;{}]/.test(resolved)||!resolved.trim())throw Error("Invalid CSS "+p);return resolved;}if(typeof resolved!=="number"||!Number.isFinite(resolved))throw Error("Invalid token "+p);return String(resolved)+(p.startsWith("motion.")?"ms":/^(spacing|radius|typography)\./.test(p)||p==="focus.ring_width"?"px":"");}
 function dart(p){let v=lookup(p);if(typeof v==="string"){if(/^#[0-9a-f]{6}$/i.test(v))return ["Color",`Color(0xFF${v.slice(1).toUpperCase()})`];if(p.endsWith(".weight")&&c.font_weights[v])return ["FontWeight",`FontWeight.w${c.font_weights[v]}`];throw Error("Invalid Dart token "+p);}if(typeof v!=="number"||!Number.isFinite(v))throw Error("Invalid token "+p);if(/^(motion|font_weights)\./.test(p)){if(!Number.isInteger(v))throw Error("Expected integer "+p);return ["int",String(v)];}return ["double",Number.isInteger(v)?v+".0":String(v)];}
 const common=groups.flatMap(g=>flatten(c[g],g));
 for(const [p] of common){let v=lookup(p);if(p.startsWith("colors.")&&!/^#[0-9a-f]{6}$/i.test(v))throw Error("Invalid color "+p);if(/^(spacing|radius|motion)\./.test(p)&&(typeof v!=="number"||v<0))throw Error("Invalid scale "+p);}
 const cssLines=["/* Generated from FHD/config/mobile_design_tokens.json. DO NOT EDIT. */",":root {"];
 for(const [p,v] of common)cssLines.push(`  --xc-token-${keb(p)}: ${css(p,v)};`);
 const marketLines=[...cssLines];
 for(const [profile,obj] of Object.entries(c.platform_overrides.market.profiles))for(const [k,v] of Object.entries(obj))marketLines.push(`  --xc-token-market-${keb(profile)}-${k}: ${css("platform_overrides.market.profiles."+profile+"."+k,v)};`);
 marketLines.push("}","");
 for(const [profile,obj] of Object.entries(c.platform_overrides.desktop.profiles))for(const [k,v] of Object.entries(obj))cssLines.push(`  --xc-token-desktop-${keb(profile)}-${k}: ${css("platform_overrides.desktop.profiles."+profile+"."+k,v)};`);
 cssLines.push("}","");
 const dartLines=["// Generated from FHD/config/mobile_design_tokens.json. DO NOT EDIT.","import 'package:flutter/material.dart';","","abstract final class DesignTokens {"],names=new Set();
 for(const [p] of [...common,...flatten(c.platform_overrides.mobile,"platform_overrides.mobile")]){let [type,v]=dart(p),name=camel(p.replace(/^platform_overrides\.mobile\./,"mobile."));if(names.has(name))throw Error("Duplicate Dart token "+name);names.add(name);dartLines.push(`  static const ${type} ${name} = ${v};`);}
 dartLines.push("}","");return {css:cssLines.join("\n"),dart:dartLines.join("\n"),market:marketLines.join("\n")};
}
const root = new URL('../../', import.meta.url);
const read = p => readFileSync(new URL(p, root), 'utf8');
const contract = JSON.parse(read('config/mobile_design_tokens.json'));
const result = render(contract);
const args = process.argv.slice(2);
if (args.length > 1 || (args.length && args[0] !== '--check')) throw Error('Usage: node generate-design-tokens.mjs [--check]');
for (const [path,content] of Object.entries({'frontend/src/styles/design-tokens.generated.css':result.css,'mobile-flutter-poc/lib/src/theme/design_tokens.generated.dart':result.dart,'../成都修茈科技有限公司/MODstore_deploy/market/src/design-tokens.generated.css':result.market})) {
  if (args[0] === '--check') {
    if (read(path) !== content) throw Error('Design token drift: '+path);
  } else writeFileSync(new URL(path,root),content,'utf8');
}
const sources = {enterprise:'frontend/src/styles/tokens.css',office_base:'frontend/src/styles/css/base.css',office:'frontend/src/styles/css/office-theme.css',professional:'frontend/src/styles/variables.css'};
for(const [profile,path] of Object.entries(sources)){
 const s=read(path);
 for(const key of Object.keys(contract.platform_overrides.desktop.profiles[profile])){
  const name='--xc-token-desktop-'+profile.replaceAll('_','-')+'-'+key;
  if(!s.includes('var('+name+')'))throw Error('Unused desktop token: '+name);
 }
 for(const [,name,value] of s.matchAll(/^[ \t]*(--[\w-]+):\s*([^;{}]+);/gm)){
  if(!value.includes('var('))throw Error('Unregistered theme literal: '+path+': '+name);
 }
}
const marketTokenSource=read('../成都修茈科技有限公司/MODstore_deploy/market/src/tokens.css');
const marketStyleSource=read('../成都修茈科技有限公司/MODstore_deploy/market/src/style.css');
if(!marketTokenSource.includes("@import './design-tokens.generated.css';"))throw Error('Market token import missing');
for(const [profile,obj] of Object.entries(contract.platform_overrides.market.profiles)){
 for(const key of Object.keys(obj)){
  const name='--xc-token-market-'+profile.replaceAll('_','-')+'-'+key;
  if(!(marketTokenSource+'\n'+marketStyleSource).includes('var('+name+')'))throw Error('Unused Market token: '+name);
 }
}
for(const [,name,value] of marketTokenSource.matchAll(/^[ \t]*(--[\w-]+):\s*([^;{}]+);/gm)){
 if(!value.includes('var('))throw Error('Unregistered Market theme literal: '+name);
}
const marketDeclarations=marketStyleSource.replace(/\/\*[\s\S]*?\*\//g,'').match(/#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)/g);
if(marketDeclarations)throw Error('Unregistered Market global color: '+marketDeclarations[0]);

const elementMappings = [["--el-color-primary","--xc-color-primary","--wb-accent-primary"],["--el-color-success","--xc-color-success","--wb-status-success"],["--el-color-warning","--xc-color-warning","--wb-status-warning"],["--el-color-danger","--xc-color-danger","--wb-status-danger"],["--el-text-color-primary","--xc-color-text","--wb-text-primary"],["--el-bg-color","--xc-color-surface","--wb-surface-elevated"],["--el-color-primary-light-9","--xc-color-primary-soft","--wb-accent-soft"]];
const desktopElements = read('frontend/src/styles/tokens.css');
for(const [elementName,desktopRef,marketRef] of elementMappings){
 if(!desktopElements.includes(elementName+': var('+desktopRef+')'))throw Error('Desktop Element Plus mapping missing: '+elementName);
 if(!marketTokenSource.includes(elementName+': var('+marketRef+')'))throw Error('Market Element Plus mapping missing: '+elementName);
}

/* Keep completed migrations from regressing. This is a scoped gate, not a
 * claim that all existing legacy components are tokenized. */
const migratedDesktopStyles = [
  'frontend/src/views/AdminBusinessCustomersView.css',
  'frontend/src/components/workflow/EmployeeWorkspaceScene.css',
];
const definedDesktopTokens = new Set(
  [...(result.css + '\n' + desktopElements).matchAll(/(--xc-[\w-]+)\s*:/g)].map(match => match[1]),
);
function migratedStyleViolations(source) {
  const css = source.replace(/\/\*[\s\S]*?\*\//g, '');
  const errors = [];
  if (/#[0-9a-f]{3,8}\b|(?:rgba?|hsla?)\(/i.test(css)) errors.push('literal color');
  for (const [, name] of css.matchAll(/var\(\s*(--xc-[\w-]+)/g)) {
    if (!definedDesktopTokens.has(name)) errors.push('undefined token ' + name);
  }
  for (const [, property, value] of css.matchAll(/(?:^|[;{])\s*(font-size|font-weight|border-radius|box-shadow|line-height|(?:margin|padding)(?:-[\w-]+)?|gap)\s*:\s*([^;{}]+)(?=[;}]|$)/gm)) {
    if (!value.includes('var(') && !/^(?:0(?:\s+0)*|inherit|none|normal)$/.test(value.trim())) {
      errors.push('unregistered ' + property + ': ' + value.trim());
    }
  }
  return errors;
}
if (migratedStyleViolations('.test { color: #123456; font-size: 19px; }').length !== 2 ||
    migratedStyleViolations('.test { color: var(--xc-not-a-real-token); }').length !== 1 ||
    migratedStyleViolations('.test { color: var(--xc-color-text); padding: 0; }').length !== 0) {
  throw Error('Migrated style audit negative/positive control failed');
}
for (const path of migratedDesktopStyles) {
  const violations = migratedStyleViolations(read(path));
  if (violations.length) throw Error('Design token consumption violation: ' + path + ': ' + violations.join(', '));
}

console.log('All three generated design-token outputs, desktop/Market aliases and migrated desktop styles verified');
