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

`454acd087f9297538809a6744643835dfa51f979` (`v1.1.1`)

Pinned map-asset version: `1.0.3.101283` (image content unchanged since
`1.0.1.100619`).
Current catalogue game-data version: `1.0.3.101283`.

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
- The container build uses the tile generator retained unchanged in upstream
  `v1.1.1`, stored as
  `docker/generate-map-tiles.py` with SHA-256
  `70cf076bdb943f00f132afa0157f6e2e5a6cb7f5de8c23c37312940167097a14`,
  Pillow `11.3.0` and libwebp `1.5.0`. It deterministically creates 680
  512x512 WebP tiles across 1024, 2048, 4096 and 8192 levels. The Palpagos
  and World Tree tile aggregate hashes are respectively
  `285f5c5ee96d11375ecee388c92653ae439bdcc6961ab45f9a3deef476630c7f`
  and `0e3639685f37200f54b30e235a05a2dd13889ddacc7de719fcf5f05e165b001f`.
  The complete generated manifest SHA-256 is
  `b1454293f3258c2db74fc51f984e864452554df9527d9146dea6992872afc261`.
- `web/dashboard/data/live-map-catalogue.json` is the Django API projection of
  the landmark datasets. It contains 1,146 locations across 11
  categories, with internal game IDs, object paths, instance IDs, state keys,
  class names, icon paths and source objects removed. Source IDs use the prior
  deterministic one-way projection. The upstream `1.0.3.101283` export records
  a 40,527,155,723-byte `Pal-Windows.pak` with SHA-256
  `c0a7d3a756ec57d3ca38d81b252d8645532bfae300c26d18426515c670531bdf`.
  Its four catalogue datasets and all map images are unchanged from
  `1.0.2.101103`; only the `Zenara & Astralym` detail changed from
  `Within the Seal` to `Sealed Sanctum`. Output SHA-256:
  `66fc7c1008062208ee8e49a4e3e0a01e0b2eaa57c78b41ba8d00e18deb0e1fe4`.
- The `v1.1.0` frontend performance work is adapted selectively: the map loads
  only visible WebP tiles at the required display density, indexes projected
  markers spatially, enforces an adaptive 300-marker render budget and loads
  the static catalogue independently from live configuration and polling. The
  Explorer lazily builds collapsed categories and fairly caps broad searches
  at 200 results.
  Django authentication, Zod contracts, local routing, multi-pointer gestures
  and the live Wild Pal/NPC layers remain local implementations.
- Upstream `v1.1.1` only upgrades its bundled `palworld-save-reader` to `v0.2.0`
  for legacy Mermaid Huffman streams. This site does not bundle that Go/GPL
  decoder or its resolve-v4 leaderboard/claim patch. Save snapshots are parsed
  on the Palworld VM by the independent `ops/PalworldGuildSync` pipeline using
  the separately pinned PalworldSaveTools/palsav implementation.
- `web/dashboard/live_map.py` adapts only already-sanitized Django snapshots to
  the upstream `PublicConfig`, `PlayerState`, `ObjectState` and
  `WorldCatalogue` contracts. The browser never receives raw Palworld player,
  trainer, guild or instance identifiers.
- The `/v1/api/game-data` actor contract, active-state semantics, identity
  deduplication, object priority and worker/base association remain independently
  implemented in Django. The collector persists only sanitized fields, opaque
  HMAC identifiers and aggregate diagnostics.

No upstream Go server, `palworld-save-reader`, GPL leaderboard patch or exporter
source code is included.

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
