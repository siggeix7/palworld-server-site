# Third-party notices

## RNZ01/palworld-server-dashboard

Parts of this project were adapted from the MIT-licensed project:

https://github.com/RNZ01/palworld-server-dashboard

Pinned upstream revision used for the 2026-07-20 integration:

`588fa6390e0c5b6fe909e2c1fd3baddb86ef92c8`

Adapted material and modifications:

- `lib/player-avatar-colors.ts`: the 12-color palette was retained; random,
  browser-local assignment was replaced by a deterministic hash of the local
  HMAC-derived public player ID.
- `components/player-roster.tsx`: public name/account search, local favorites
  and ping thresholds were adapted without raw IDs or moderation actions.
- `components/server-control-cards.tsx`: FPS gap detection and the composite
  health model were moved server-side and rewritten for the local 20-second
  collection cadence, time-weighted coverage and dynamic gap thresholds.
- `lib/palworld.ts`: alternate player payload field names were added to the
  ingest sanitizer. Raw player/user IDs are discarded; the last observed game
  IP is retained separately for security and moderation and is available only
  to configured site administrators.
- `lib/theme-context.tsx`: theme names and accent palette were adapted to the
  Observatory design system. The current SPA implements those themes with
  React and Tailwind; no Radix implementation was copied.

The public site exposes a condensed notice through
`web/dashboard/static/dashboard/THIRD_PARTY_NOTICES.txt`.

No RNZ01 administrative proxy, authentication, password storage, kick/ban,
announcement, save, shutdown, restart, chat or raw console code is included.
No Gridcn components or npm dependencies were copied from RNZ01 during this
integration.

## LukeHollandDev/palworld-live-map

The authenticated map embeds and adapts the MIT-licensed React interface and
the Palworld map/catalogue workflow from:

https://github.com/LukeHollandDev/palworld-live-map

Pinned upstream revision:

`19f3e3f8e684481bde58fef6c76845f811d57614`

Pinned map-asset version: `1.0.1.100619`.
Current catalogue game-data version: `1.0.2.101103`.

- `web/live-map/` contains the upstream React 19, TypeScript, Vite and Tailwind
  client. Local changes integrate the former Django dashboard into the same SPA,
  add React Router navigation and Zod validation, point all features at
  authenticated Django endpoints and produce deterministic bundle names. The
  complete upstream MIT license is retained in `web/live-map/LICENSE`.
- `web/dashboard/static/dashboard/live-map/maps/palpagos.jpg` and
  `world-tree.jpg` are the original 8192x8192 upstream assets. Their SHA-256
  hashes are respectively
  `9961632d5c38a0a67fd18713fa63af0ac6f192e71fadeb5ba53ae696b8914dd1`
  and `77fee7b2bb90fa62f26eeb862396d54dbc8c7d2f0f5b12339c12585474f7c521`.
- `web/dashboard/data/live-map-catalogue.json` is the Django API projection of
  the landmark datasets. It contains 1,146 locations across 11
  categories, with internal game IDs, object paths, instance IDs, state keys,
  class names, icon paths and source objects removed. Source IDs use the prior
  deterministic one-way projection. The `1.0.2.101103` export was verified
  against Pocketpair's official `ghcr.io/pocketpairjp/palserver` image digest
  `sha256:09343cac3d92b997634f034ade4ce702388e156ec726668c85ad3bc47faa33f4`;
  its `Pal-LinuxServer.pak` SHA-256 is
  `94a364adc846c148c27af907231b37a20f1096f0f93c3022636b68de40f5294c`.
  All 1,146 projected locations are unchanged from `1.0.1.100619`. Output
  SHA-256: `04a51a485cdad67d6b207fe5e2778fa0346bafbc62645ba7142dbc939e4acbff`.
- `web/dashboard/live_map.py` adapts only already-sanitized Django snapshots to
  the upstream `PublicConfig`, `PlayerState`, `ObjectState` and
  `WorldCatalogue` contracts. The browser never receives raw Palworld player,
  trainer, guild or instance identifiers.
- The `/v1/api/game-data` actor contract, active-state semantics, identity
  deduplication, object priority and worker/base association remain independently
  implemented in Django. The collector persists only sanitized fields, opaque
  HMAC identifiers and aggregate diagnostics.

No upstream Go server or exporter source code is included.

### Luke Holland MIT License

MIT License

Copyright (c) 2026 Luke Holland

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

### React and ReactDOM MIT License

MIT License

Copyright (c) Meta Platforms, Inc. and affiliates.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

### Tabler Icons MIT License

MIT License

Copyright (c) 2020-2026 Paweł Kuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

### RNZ01 MIT License

MIT License

Copyright (c) 2026 Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Pocketpair material

The software licenses referenced above do not grant rights to Palworld artwork,
trademarks or game data owned by Pocketpair, Inc. The map images originate from
Palworld game data. Palworld and the map artwork are trademarks and copyrighted
material of Pocketpair, Inc. This project is an unofficial community dashboard
and is not affiliated with or endorsed by Pocketpair. Anyone redistributing the
maps must independently verify that the intended use complies with applicable
Pocketpair terms and fan-content rules:

https://www.pocketpair.jp/en/guidelines-derivativework-en/
