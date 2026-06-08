/**
 * M0 证据链 · staging SLO 四域 + Mod 试点四图
 * 读取 FHD/docs/evidence/m0-evidence-manifest.json 并渲染 #mon-m0-evidence
 */
(function () {
  'use strict';

  const MANIFEST_URL = 'FHD/docs/evidence/m0-evidence-manifest.json';
  const SLO_BASE = 'FHD/docs/evidence/slo/';
  const MOD_BASE = 'FHD/docs/evidence/mod/';

  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function windowProgress(st) {
    if (!st || !st.window_started_at) return null;
    const start = new Date(st.window_started_at + 'T00:00:00Z');
    if (isNaN(start.getTime())) return null;
    const target = st.window_target_days || 7;
    const elapsedRaw = Math.floor((Date.now() - start.getTime()) / 86400000) + 1;
    const day = Math.max(1, Math.min(elapsedRaw, target));
    return { day, target, done: elapsedRaw >= target };
  }

  function statusClass(status) {
    if (status === 'pass') return 'ok';
    if (status === 'partial' || status === 'observing') return 'warn';
    return 'fail';
  }

  function statusLabel(status) {
    if (status === 'pass') return '已验收';
    if (status === 'observing') return '实时计时中';
    if (status === 'partial') return '本地预览';
    return '未就位';
  }

  function previewTier(preview) {
    if (preview === 'accepted' || preview === 'verified') return 'ok';
    if (preview === 'staging_live' || preview === 'grafana' || preview === 'metrics') return 'warn';
    return 'fail';
  }

  function previewBadge(preview, present) {
    if (!present) return '✗';
    if (preview === 'accepted' || preview === 'verified') return '✓';
    if (preview === 'staging_live' || preview === 'grafana' || preview === 'metrics') return '◐';
    return '✗';
  }

  function panelCardClass(present, preview) {
    if (!present) return 'fail';
    return previewTier(preview);
  }

  function renderPanelCard(panel, base, kind, sectionStatus) {
    const present = panel.present;
    const preview = panel.preview || 'scaffold';
    const cls = panelCardClass(present, preview);
    const imgSrc = base + panel.filename;
    const previewTag =
      preview === 'scaffold'
        ? '脚手架 · 非验收'
        : preview === 'accepted'
          ? '7d 验收'
          : preview === 'staging_live'
            ? 'staging 实时真图 · 7d 计时中'
            : preview === 'grafana'
              ? 'Grafana 真图'
              : preview === 'metrics'
                ? '/metrics 预览'
                : preview === 'local'
                  ? '本地预览'
                  : '';
    const imgBlock = present
      ? `<img class="mon-evidence-img" src="${esc(imgSrc)}?v=${encodeURIComponent(preview)}&b=${panel.bytes || 0}" alt="${esc(panel.title)}" loading="lazy" />${
          previewTag ? `<div class="mon-evidence-preview-tag">${esc(previewTag)}</div>` : ''
        }`
      : `<div class="mon-evidence-placeholder">
           <span class="mon-evidence-ph-icon">${kind === 'staging' ? '⏳' : '📊'}</span>
           <span class="mon-evidence-ph-title">${esc(panel.title)}</span>
           <span class="mon-evidence-ph-sub">${kind === 'staging' ? 'T36–T37 · 需 staging 7 天流量' : '运行 local_stack_up.sh 或 render 脚本'}</span>
           <code class="mon-evidence-ph-file">${esc(panel.filename)}</code>
         </div>`;

    return `<div class="mon-evidence-card ${cls}" data-panel="${esc(panel.uid + ':' + panel.panel_id)}">
      <div class="mon-evidence-card-head">
        <span class="mon-evidence-badge ${cls}">${previewBadge(preview, present)}</span>
        <div>
          <div class="mon-evidence-card-title">${esc(panel.title)}</div>
          <div class="mon-evidence-card-meta">${esc(panel.uid)}:${panel.panel_id}${panel.slo_id ? ' · ' + esc(panel.slo_id) : ''}</div>
        </div>
        <span class="mon-evidence-target">${esc(panel.target)}</span>
      </div>
      <div class="mon-evidence-card-body">${imgBlock}</div>
    </div>`;
  }

  function renderModCard(step, sectionStatus) {
    const present = step.present;
    const preview = step.preview || 'path';
    const cls = panelCardClass(present, preview);
    const previewTag =
      preview === 'path' ? '路径预览 · 非流水' : preview === 'verified' ? '商家流水' : '';
    const imgBlock = present
      ? `<img class="mon-evidence-img" src="${esc(MOD_BASE + step.file)}?v=${encodeURIComponent(preview)}" alt="${esc(step.title)}" loading="lazy" />${
          previewTag ? `<div class="mon-evidence-preview-tag mod">${esc(previewTag)}</div>` : ''
        }`
      : `<div class="mon-evidence-placeholder mod">
           <span class="mon-evidence-ph-step">${step.step}</span>
           <span class="mon-evidence-ph-title">${esc(step.title)}</span>
           <span class="mon-evidence-ph-sub">${esc(step.action)}</span>
           <code class="mon-evidence-ph-file">${esc(step.file)}</code>
         </div>`;

    return `<div class="mon-evidence-card ${cls}" data-mod-step="${step.step}">
      <div class="mon-evidence-card-head">
        <span class="mon-evidence-badge ${cls}">${previewBadge(preview, present)}</span>
        <div>
          <div class="mon-evidence-card-title">步骤 ${step.step} · ${esc(step.title)}</div>
          <div class="mon-evidence-card-meta">${esc(step.action)}</div>
        </div>
      </div>
      <div class="mon-evidence-card-body">${imgBlock}</div>
    </div>`;
  }

  function renderManifest(data) {
    const root = document.getElementById('mon-m0-evidence');
    if (!root || !data) return;

    const st = data.staging_slo || {};
    const loc = data.local_slo || {};
    const mod = data.mod_pilot || {};
    const disp = data.display || {};

    const wp = windowProgress(st);
    const stagingHeadline = wp
      ? `${wp.done ? '✅' : '⏳'} staging SLO 四图 · 实时真图 ${st.live_ready ?? 4}/4 · 7d 验收计时 Day ${wp.day}/${wp.target}（起算 ${esc(st.window_started_at)}）`
      : (disp.staging_slo_headline || '');
    const stagingSectionLabel = wp
      ? (wp.done ? '7d 观测已满 · 待导出验收 YAML' : `实时计时中 Day ${wp.day}/${wp.target}`)
      : statusLabel(st.status);

    root.innerHTML = `
      <div class="mon-evidence-hero">
        <div class="mon-evidence-hero-item ${statusClass(st.status)}">
          <div class="mon-evidence-hero-num">${(st.live_ready != null ? st.live_ready : (st.acceptance_ready ?? 0))}/${st.total || 4}</div>
          <div class="mon-evidence-hero-label">staging SLO 四图</div>
          <div class="mon-evidence-hero-status">${esc(stagingHeadline)}</div>
          <div class="mon-evidence-hero-blocker">${esc(st.blocker || '')}</div>
        </div>
        <div class="mon-evidence-hero-item ${statusClass(mod.status)}">
          <div class="mon-evidence-hero-num">${mod.verified_ready ?? 0}/${mod.total || 4}</div>
          <div class="mon-evidence-hero-label">Mod 试点四图</div>
          <div class="mon-evidence-hero-status">${esc(disp.mod_pilot_headline || '')}</div>
          <div class="mon-evidence-hero-blocker">${esc(mod.blocker || '')}</div>
        </div>
        <div class="mon-evidence-hero-item ${statusClass(loc.status)}">
          <div class="mon-evidence-hero-num">${(loc.grafana_ready != null ? loc.grafana_ready : loc.ready) || 0}/${loc.total || 4}</div>
          <div class="mon-evidence-hero-label">本地 SLO 预览</div>
          <div class="mon-evidence-hero-status">${esc(disp.local_slo_headline || '')}</div>
          <div class="mon-evidence-hero-blocker">${esc(loc.note || '')}</div>
        </div>
      </div>

      <div class="mon-evidence-section">
        <div class="mon-evidence-section-head">
          <h3>staging SLO 四域 · M0 #1 · ${esc(stagingSectionLabel)}</h3>
          <span class="mon-evidence-ts">manifest ${esc(data.generated_at || '')}</span>
        </div>
        <div class="mon-evidence-grid">${(st.panels || []).map((p) => renderPanelCard(p, SLO_BASE, 'staging', st.status)).join('')}</div>
      </div>

      <div class="mon-evidence-section">
        <div class="mon-evidence-section-head">
          <h3>本地 SLO 预览 · 脚手架验证 · ${statusLabel(loc.status)}</h3>
          <code>bash FHD/scripts/observability/local_stack_up.sh</code>
        </div>
        <div class="mon-evidence-grid">${(loc.panels || []).map((p) => renderPanelCard(p, SLO_BASE, 'local', loc.status)).join('')}</div>
      </div>

      <div class="mon-evidence-section">
        <div class="mon-evidence-section-head">
          <h3>Mod 商家试点四图 · M0 #2 · ${statusLabel(mod.status)}</h3>
          <code>bash FHD/MODstore/scripts/mod-pilot-checklist.sh --verify</code>
        </div>
        <div class="mon-evidence-grid mod">${(mod.steps || []).map((s) => renderModCard(s, mod.status)).join('')}</div>
      </div>

      <div class="mon-evidence-foot">
        <b>诚实口径</b>：staging 四图现为 <b>k3s xcagi-staging 实时 Grafana 真图</b>（now-7d 窗口），但 <b>7 天连续观测计时未满 ≠ 已验收</b>；满 7d 后由
        <code>ssh root@119.27.178.147 'bash /opt/collect_7day_k8s.sh'</code> 导出验收 PNG + acceptance YAML 才算闭环。
        Mod 四图需真实商家流水；本地预览 PNG 仅验证 dashboard JSON / 导出脚本。
      </div>`;

    root.removeAttribute('hidden');
    root.setAttribute('data-loaded', 'true');

    const sub = document.getElementById('mon-hero-m0-sub');
    if (sub) {
      sub.textContent = `${stagingHeadline} · ${disp.mod_pilot_headline || ''} · ${disp.local_slo_headline || ''}`;
    }
  }

  function renderFallback(msg) {
    const root = document.getElementById('mon-m0-evidence');
    if (!root) return;
    root.innerHTML = `<div class="mon-evidence-foot fail">${esc(msg)}</div>`;
    root.removeAttribute('hidden');
  }

  async function load() {
    const root = document.getElementById('mon-m0-evidence');
    if (!root) return;
    try {
      const data =
        window.XCAGIApi && typeof window.XCAGIApi.fetchJson === 'function'
          ? await window.XCAGIApi.fetchJson(MANIFEST_URL, { cache: 'no-store' })
          : null;
      if (!data) throw new Error('manifest unavailable');
      renderManifest(data);
    } catch (e) {
      renderFallback(`无法加载 ${MANIFEST_URL}：${e.message}。请先运行 python3 FHD/scripts/observability/render_m0_evidence_previews.py`);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }

  document.addEventListener('xcagi-tab-shown', (ev) => {
    if (ev.detail && ev.detail.tab === 'monitor') load();
  });
})();
