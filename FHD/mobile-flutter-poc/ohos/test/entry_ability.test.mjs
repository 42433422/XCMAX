// node --experimental-vm-modules --test ohos/test/entry_ability.test.mjs
// Run the actual ArkTS glue with platform boundary doubles and real filesystem paths.
// The HAP build separately checks the SDK types; system UI still needs device acceptance.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createContext, SourceTextModule, SyntheticModule } from 'node:vm';

const source = fs.readFileSync(new URL('../entry/src/main/ets/entryability/EntryAbility.ets', import.meta.url), 'utf8');

async function runner(t, show = async () => {}) {
  const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-harmony-'));
  t.after(() => fs.rmSync(cacheDir, { recursive: true, force: true }));
  const channels = new Map();
  const shares = [];
  const plugins = [];
  const lifecycle = [];
  const engine = {
    getDartExecutor: () => ({ getBinaryMessenger: () => ({}) }),
    getPlugins: () => ({ add: plugin => plugins.push(plugin) }),
  };
  class FlutterAbility {
    context = { cacheDir };
    onCreate(want, params) { lifecycle.push(['create', want, params]); this.configureFlutterEngine(engine); }
    onNewWant(want, params) { lifecycle.push(['want', want, params]); }
    configureFlutterEngine() {}
    cleanUpFlutterEngine() { lifecycle.push(['cleanup']); }
  }
  class MethodChannel {
    outgoing = [];
    constructor(_messenger, name) { channels.set(name, this); }
    setMethodCallHandler(handler) { this.handler = handler; }
    invokeMethod(method, argument) { this.outgoing.push({ method, argument }); }
  }
  class ShareController {
    constructor(data) { this.data = data; }
    async show(context, options) { shares.push({ data: this.data, context, options }); await show(); }
  }
  const modules = {
    '@kit.AbilityKit': { AbilityConstant: {}, Want: {}, common: {} },
    '@kit.ArkTS': { url: { URL: { parseURL: value => new URL(value) } } },
    '@kit.CoreFileKit': { fileIo: { lstatSync: fs.lstatSync }, fileUri: { getUriFromPath: value => pathToFileURL(value).href } },
    '@kit.ArkData': { uniformTypeDescriptor: {
      UniformDataType: { FILE: 'general.file' },
      getUniformDataTypeByFilenameExtension: extension => `file${extension}`,
    } },
    '@kit.ShareKit': { systemShare: {
      SharedData: class { constructor(record) { this.record = record; } },
      ShareController, SharePreviewMode: { DETAIL: 1 }, SelectionMode: { SINGLE: 0 },
    } },
    '@ohos/flutter_ohos': { FlutterAbility, FlutterEngine: class {}, MethodChannel, MethodCall: class {}, MethodCallHandler: {}, MethodResult: {} },
    '../plugins/GeneratedPluginRegistrant': { GeneratedPluginRegistrant: { registerWith: () => plugins.push('generated') } },
    '../plugins/XcagiPlatformPlugin': { default: class PlatformPlugin {} },
    '../plugins/XcagiScanPlugin': { default: class ScanPlugin {} },
  };
  const context = createContext({ console });
  const module = new SourceTextModule(stripTypeScriptTypes(source), { context });
  await module.link(specifier => {
    const exports = modules[specifier];
    assert.ok(exports, `Unexpected platform import: ${specifier}`);
    return new SyntheticModule(Object.keys(exports), function () {
      for (const [name, value] of Object.entries(exports)) this.setExport(name, value);
    }, { context });
  });
  await module.evaluate();
  const ability = new module.namespace.default();
  function call(channel, method, args = {}) {
    return new Promise((resolve, reject) => {
      const handler = channels.get(channel)?.handler;
      if (!handler) { reject(new Error(`MissingPluginException: ${channel}`)); return; }
      handler.onMethodCall({ method, argument: name => args[name] }, {
        success: resolve,
        error: (code, message) => reject(Object.assign(new Error(message), { code })),
        notImplemented: () => reject(Object.assign(new Error('not implemented'), { code: 'not_implemented' })),
      });
    });
  }
  const root = path.join(cacheDir, 'workspace_exports');
  const directory = path.join(root, 'export-example');
  fs.mkdirSync(directory, { recursive: true });
  const file = path.join(directory, '材料 清单.xlsx');
  fs.writeFileSync(file, 'exported bytes');
  return { ability, engine, call, channels, shares, plugins, lifecycle, cacheDir, root, directory, file };
}

test('export opens the system share panel for the exact local file and waits for it', async t => {
  let opened;
  const panel = new Promise(resolve => { opened = resolve; });
  const r = await runner(t, () => panel);
  r.ability.onCreate({}, {});
  let done = false;
  const pending = r.call('xcagi/workspace_files', 'share', { path: r.file }).then(() => { done = true; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(done, false);
  assert.equal(r.shares.length, 1);
  assert.equal(fileURLToPath(r.shares[0].data.record.uri), r.file);
  assert.equal(r.shares[0].data.record.utd, 'file.xlsx');
  assert.equal(r.shares[0].data.record.title, '材料 清单.xlsx');
  assert.equal(r.shares[0].context, r.ability.context);
  opened();
  await pending;
  assert.equal(done, true);
  assert.equal(r.plugins.length, 3); // Generated plugins, HUKS/session storage and scanning remain registered.
});

test('export never reports success when the system share panel fails', async t => {
  const r = await runner(t, async () => { throw new Error('UI unavailable'); });
  r.ability.onCreate({}, {});
  await assert.rejects(r.call('xcagi/workspace_files', 'share', { path: r.file }), { code: 'file_export' });
});

test('export refuses non-export files, traversal, symlinks, directories and missing files', async t => {
  const r = await runner(t);
  r.ability.onCreate({}, {});
  const secret = path.join(r.cacheDir, 'xcagi_session.json');
  fs.writeFileSync(secret, 'must not be shared');
  const link = path.join(r.directory, 'secret.xlsx');
  fs.symlinkSync(secret, link);
  const linkedDirectory = path.join(r.root, 'linked');
  fs.symlinkSync(r.cacheDir, linkedDirectory);
  for (const file of [undefined, 42, secret, r.directory, r.root + '-other/a.xlsx',
    r.root + '/../xcagi_session.json', link, linkedDirectory + '/xcagi_session.json',
    r.directory + '/missing.xlsx', r.directory + '/..//export-example/材料 清单.xlsx']) {
    await assert.rejects(r.call('xcagi/workspace_files', 'share', { path: file }), { code: 'file_export' });
  }
  assert.equal(r.shares.length, 0);
});

test('cold start consumes payment URI once, and a warm return reaches the existing route stream', async t => {
  const r = await runner(t);
  const initial = { uri: 'xcagi://payment/complete?order_id=A%2FB' };
  r.ability.onCreate(initial, {});
  assert.equal(await r.call('xcagi/deep_link', 'getInitialRoute'), 'payment/complete?order_id=A%2FB');
  assert.equal(await r.call('xcagi/deep_link', 'getInitialRoute'), null);
  const warm = { uri: 'xcagi://payment/complete?order_id=C' };
  r.ability.onNewWant(warm, {});
  const sent = r.channels.get('xcagi/deep_link').outgoing;
  assert.equal(sent.length, 1);
  assert.equal(sent[0].method, 'onRoute');
  assert.equal(sent[0].argument, 'payment/complete?order_id=C');
  assert.deepEqual(r.lifecycle.map(event => event[0]), ['create', 'want']);
});

test('a new URI received before Dart subscribes remains available to the initial route call', async t => {
  const r = await runner(t);
  r.ability.onCreate({}, {});
  r.ability.onNewWant({ uri: 'xcagi://payment/complete' }, {});
  assert.equal(r.channels.get('xcagi/deep_link').outgoing.length, 0);
  assert.equal(await r.call('xcagi/deep_link', 'getInitialRoute'), 'payment/complete');
  assert.equal(await r.call('xcagi/deep_link', 'getInitialRoute'), null);
});

test('foreign, malformed and credential-bearing links never become app routes', async t => {
  const r = await runner(t);
  r.ability.onCreate({}, {});
  await r.call('xcagi/deep_link', 'getInitialRoute');
  for (const uri of ['', 'invalid', 'https://attacker.example/payment/complete',
    'xcagi-evil://payment/complete', 'xcagi://user:secret@payment/complete',
    'xcagi://payment:1234/complete', 'xcagi:///payment/complete']) r.ability.onNewWant({ uri }, {});
  assert.equal(r.channels.get('xcagi/deep_link').outgoing.length, 0);
  assert.equal(await r.call('xcagi/deep_link', 'getInitialRoute'), null);
});

test('engine cleanup unregisters both channels, and unknown methods remain unsupported', async t => {
  const r = await runner(t);
  r.ability.onCreate({}, {});
  for (const channel of ['xcagi/workspace_files', 'xcagi/deep_link']) {
    await assert.rejects(r.call(channel, 'unrecognized'), { code: 'not_implemented' });
  }
  r.ability.cleanUpFlutterEngine(r.engine);
  assert.equal(r.channels.get('xcagi/workspace_files').handler, null);
  assert.equal(r.channels.get('xcagi/deep_link').handler, null);
  assert.equal(r.lifecycle.at(-1)[0], 'cleanup');
});

test('the exported singleton ability accepts the payment-return scheme', () => {
  const manifest = JSON.parse(fs.readFileSync(new URL('../entry/src/main/module.json5', import.meta.url), 'utf8'));
  const ability = manifest.module.abilities.find(item => item.name === 'EntryAbility');
  assert.equal(ability.exported, true);
  assert.equal(ability.launchType, 'singleton');
  assert.ok(ability.skills.some(skill => skill.actions.includes('ohos.want.action.viewData') &&
    skill.entities.includes('entity.system.browsable') && skill.uris?.some(uri => uri.scheme === 'xcagi')));
});
