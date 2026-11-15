# Static chart security boundary

Review scope: `05-intent-tool-routing-architecture.html`, `assets/charts.js`,
and its sole vendored Apache ECharts 5.5.1 bundle.
Bundle SHA-256: `e84270bd0cd5bdf60fefc26d00c2a391cb2e81f4d26a7a9ee16185a54773a3cf`.

## Actual inputs and regression coverage

The sole caller constructs fourteen literal name/number rows. It reads no URL,
query, fragment, network, message, storage or user-provided chart configuration.
Theme colors come from local CSS properties. It enables SVG, a bar series,
a percentage mark line, labels, an axis tooltip and resize handling.

The tooltip now returns DOM text nodes with a real line break, not raw HTML.
This preserves its display while preventing label injection if a future caller
adds external data. `node --test assets/charts.test.cjs` tests hostile labels,
all fourteen rows, formatting, resize, actual vendored SVG SSR and JSON parsing.
The hostile-label regression fails against the previous HTML-string formatter.

## Independent findings assessment

- `html-inline-event-handler`: the regex starts at JavaScript comparison
  `<a.length;h++)`, then crosses 4,811 characters until `.onclick=`. This is
  not an HTML element or an HTML inline event attribute.
- `html-innerhtml-assignment`: constant empty/null assignments clear renderers;
  connected SVG export consumes the renderer's generated SVG and is not called;
  toolbox dataView title/lang/optionToContent sinks require an enabled dataView,
  which this caller never configures. The remaining tooltip sink accepts raw
  strings by design; our formatter now supplies DOM text nodes instead.
- `html-document-write`: the sole call belongs to the toolbox saveAsImage
  browser fallback. No toolbox/saveAsImage exists in this chart. No external
  title, filename or image URL is supplied.
- `js-new-function-string`: the sole occurrence is the legacy GeoJSON fallback
  when JSON.parse is unavailable. Modern runtimes take JSON.parse; our chart
  does not register maps or accept GeoJSON. The regression confirms non-JSON
  JavaScript expressions are rejected by the actual bundled modern code path.

The vendor APIs are not intrinsically safe for arbitrary untrusted options.
This assessment is specific to the inspected caller, not a blanket exemption.
The bundle, all scanner rules, accounting and checks remain unchanged. This
note is evidence, not an approval, suppression or permission to bypass a gate.

## Upstream references and known advisory scope

- https://echarts.apache.org/handbook/en/best-practices/security/
  documents trusted-input requirements and DOM-element tooltip formatters.
- https://github.com/apache/echarts/pull/21640 removes the legacy GeoJSON eval
  fallback upstream; current static bar input never reaches it.
- CVE-2026-45249 / https://github.com/apache/echarts/pull/21608 concerns the
  default Lines-series tooltip. This caller uses bar plus its own DOM formatter,
  not Lines or its default formatter. Do not reuse this conclusion for new APIs.
