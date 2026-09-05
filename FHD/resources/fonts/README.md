# Embedded label font

Label PDF output uses a static regular instance of Noto Sans SC, embedded as a PDF subset. It must not depend on Adobe-GB1 language packs or a customer machine's installed fonts. Keep `NotoSansSC-Regular.ttf` and `OFL-NotoSansSC.txt` together in every distribution.

Upstream: [Google Fonts Noto Sans SC](https://github.com/google/fonts/tree/2894aab31764f10f29c421bdfd2340d3b382d384/ofl/notosanssc), commit `2894aab31764f10f29c421bdfd2340d3b382d384`.

- Original: `NotoSansSC[wght].ttf`, 17,772,300 bytes, SHA256 `a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da`.
- Bundled static instance: `NotoSansSC-Regular.ttf`, weight 400, 30,890 mapped Unicode code points, 10,595,932 bytes, SHA256 `eeb06b8a64fd04a2744d95579db1571b51027cda61ed78c62e4b730791525461`.
- License text from upstream `OFL.txt`, with trailing whitespace normalized: bundled SHA256 `babcfe66c8a098b2fa279bc724a3a342f8124f77ce18941fbcc1bbb39823cded`; original SHA256 `1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9`. SIL Open Font License 1.1. This font retains its upstream license, distinct from the application's license.

Reproduce with Python and `fonttools==4.60.2` in a separate development environment; FontTools is not a product runtime dependency:

```python
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
font = TTFont("NotoSansSC[wght].ttf", recalcTimestamp=False)
font = instantiateVariableFont(font, {"wght": 400}, inplace=True, updateFontNames=True)
font.recalcTimestamp = False
font.save("NotoSansSC-Regular.ttf")
```

The desktop PyInstaller spec validates both files before collecting `resources`; the production Dockerfile copies the same directory. The renderer resolves this path relative to its bundled application root. Never silently fall back to an unembedded CID font if the resource or a required glyph is absent.
