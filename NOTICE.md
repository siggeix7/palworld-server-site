# Third-party notices

## RNZ01/palworld-server-dashboard

Parts of this project were adapted from the MIT-licensed project:

https://github.com/RNZ01/palworld-server-dashboard

Pinned upstream revision used for the 2026-07-20 integration:

`588fa6390e0c5b6fe909e2c1fd3baddb86ef92c8`

Adapted material and modifications:

- `components/live-map.tsx`: coordinate projection, layer preference, cursor-
  anchored zoom, edge-clamped pan, marker grouping and gap-free interaction
  concepts were rewritten in vanilla JavaScript in
  `web/dashboard/static/dashboard/js/site.js`. Pointer and keyboard support,
  player trails and accessible cluster controls are local modifications.
- `lib/player-avatar-colors.ts`: the 12-color palette was retained; random,
  browser-local assignment was replaced by a deterministic hash of the local
  HMAC-derived public player ID.
- `components/player-roster.tsx`: public name/account search, local favorites
  and ping thresholds were adapted without raw IDs or moderation actions.
- `components/server-control-cards.tsx`: FPS gap detection and the composite
  health model were moved server-side and rewritten for the local 20-second
  Zabbix cadence, time-weighted coverage and dynamic gap thresholds.
- `lib/palworld.ts`: alternate player payload field names were added to the
  ingest sanitizer. Raw player/user IDs and IP addresses are still discarded.
- `lib/theme-context.tsx`: theme names and accent palette were adapted to the
  existing Observatory CSS variables without React, Tailwind or Radix.
- `public/palworld-map/full-map-native-8192.webp`: the Palpagos overview was
  subsequently updated to the 8192x8192 Palworld 1.0 map distributed locally as
  `web/dashboard/static/dashboard/images/palworld-map.webp`, SHA-256
  `34f67e2e02a9c573d7c2c229207844407a852b7e016f9796b9603e0db3115a86`.
  Its matching bounds are `[349400, 724400, -1099400, -724400]`. Local 2048
  and 4096 WebP derivatives reduce transfer and decode cost on smaller screens.

The public site exposes a condensed notice through
`web/dashboard/static/dashboard/THIRD_PARTY_NOTICES.txt`.

No RNZ01 administrative proxy, authentication, password storage, kick/ban,
announcement, save, shutdown, restart, chat or raw console code is included.
No Gridcn components or npm dependencies were copied from RNZ01 during this
integration.

## LukeHollandDev/palworld-live-map

The Palworld 1.0.1 map manifest and static navigation catalogues were generated
by the reproducible exporter documented at:

https://github.com/LukeHollandDev/palworld-live-map

Pinned upstream revision:

`19f3e3f8e684481bde58fef6c76845f811d57614`

Pinned game-data version: `1.0.1.100619`.

- `assets/palworld/maps/world-tree.jpg`: native 8192x8192 World Tree overview,
  source SHA-256
  `77fee7b2bb90fa62f26eeb862396d54dbc8c7d2f0f5b12339c12585474f7c521`,
  converted locally to WebP at
  `web/dashboard/static/dashboard/images/palworld-map-world-tree.webp`,
  SHA-256
  `8a08427dc41f25189dbab4c8e15ad529c35b0e36b2901e426203a4ff5dd03ec2`.
  Its matching bounds are `[689148.5, -476400, 347351.5, -818197]`. Local 2048
  and 4096 WebP derivatives are served adaptively.
- `assets/palworld/landmarks/manifest.json` and the `encounter-additions`,
  `navigation`, `collectibles` and `npc-locations` catalogues: factual names,
  coordinates, levels, descriptions and public rewards were minimized into
  `web/dashboard/static/dashboard/data/map-points.json`. It contains 1,146
  locations across 11 categories: 1,064 in Palpagos and 82 in the World Tree
  region. Internal game IDs, object paths, instance IDs, state keys, class names,
  icon paths and source objects are not included. Source IDs are replaced with
  deterministic one-way hashes. Output SHA-256:
  `c3b747e3f1686952e1a871c6785779275ef087af07caab44db260afdf5cb02e6`.
- `web/dashboard/management/commands/build_map_catalogue.py` is the local,
  independently written minimizer. It validates the pinned source manifests,
  hashes, counts, categories and map bounds before producing deterministic JSON.
- Search, category filtering, marker details, viewport culling, grid clustering
  and responsive explorer behavior in `site.js`, `site.css` and `map.html` were
  implemented locally for the existing privacy-sanitized Django map after
  reviewing the upstream React interface. No React or Go application code is
  included.

No application or exporter code from this project is included.

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
