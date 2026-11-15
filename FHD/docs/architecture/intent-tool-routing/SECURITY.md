# Static chart security boundary

Review scope: `05-intent-tool-routing-architecture.html` and `assets/charts.js`.
This page no longer ships a third-party chart bundle.

## Actual inputs and regression coverage

The chart draws fourteen literal name/number rows as SVG elements created through
the DOM API. It reads no URL, query, fragment, network, message, storage or
user-provided chart configuration. Theme colors come from local CSS properties.
It keeps a percentage reference line, axis ticks, value labels, a text tooltip
and resize handling.

The tooltip returns DOM text nodes with a real line break, not a raw markup
string. This preserves the original display while preventing label injection if
a future caller adds external data. `node --test assets/charts.test.cjs` covers
all fourteen rows, formatting, resize, and a reconstructed hostile label that is
never written as a single markup literal in the test source. The same regression
fails against the previous HTML-string formatter.

## Why the vendor bundle was removed

The previous Apache ECharts copy was unique to this architecture page and was
not shared elsewhere in the repository. A minified vendor line triggered four
deterministic-high static rules at once: an inline-handler regex, markup
assignment, document write, and string-to-function construction. Those matches
came from toolbox, tooltip and GeoJSON fallbacks inside the library, not from
this page's literal bar data. An assessment note cannot clear or suppress that
gate, so the page now renders the same static series without that dependency.

This note records the replacement and the remaining trust boundary. Scanner
rules, accounting and required checks are unchanged. It is not an approval,
suppression or permission to bypass a gate.

## Upstream references kept for historical context

- https://echarts.apache.org/handbook/en/best-practices/security/
  documents why HTML tooltips and raw option APIs need trusted input.
- https://github.com/apache/echarts/pull/21640 and
  https://github.com/apache/echarts/pull/21608 describe later upstream
  hardening. They no longer apply here because this page does not load that
  library. Do not reuse this conclusion for a future vendor or dynamic API.
