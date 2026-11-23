# Pixel Agents office renderer

Source: <https://github.com/pixel-agents-hq/pixel-agents>, **v1.6.0**, commit
`4dd14d612fd37d89ffbbc977959f572395c4eec8`. Code and bundled office furniture:
MIT, Copyright (c) 2026 Pablo De Lucca; see `LICENSE`.

The character art is derived upstream from JIK-A-4's MetroCity pack, published
under CC0: <https://jik-a-4.itch.io/metrocity-free-topdown-character-pack>.
`atlas.png` composes the six unchanged upstream default characters, six furniture
families, one floor and one wall sheet. It contains no Star Office assets.

This subset preserves the upstream Canvas 2D renderer, state machine, sprite
cache, furniture pairing, layout conversion, pathfinding and animation loop.
`upstream.json` records the original SHA-256 of each source file. The only source
adaptation removes the unused React hook and card store from `contextGauge.ts`;
its pure functions remain unchanged. No React, CLI, PTY, server or editor UI is
included in the application.

Reproduce with a clean upstream checkout at the pinned commit and the frontend
development dependencies installed:

```sh
node FHD/third_party/pixel-agents/vendor.mjs /path/to/pixel-agents
```

The Vue adapter maps the existing employee/task SSOT into this renderer. It
keeps inactive employees seated, disables random wandering between departments,
pauses off-screen/reduced-motion animation, and never invents task transitions.
