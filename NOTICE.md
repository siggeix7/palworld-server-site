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
- `lib/map-points.json`: seven tower and 81 validated fast-travel coordinates
  are present in `web/dashboard/static/dashboard/data/map-points.json`. The
  ambiguous upstream point `[6, -1]` is intentionally omitted.
- `public/palworld-map/full-map-native-8192.webp`: distributed locally as
  `web/dashboard/static/dashboard/images/palworld-map.webp`, byte-identical to
  Git blob `b7b2db97749bd8715bb6ebcb9d9b62eacac61ff2` with SHA-256
  `26b4a2564820db2d085b5462293891a99676ce98dc5bf11680bfa3f6784f0816`.
  Its matching MainMap bounds are `[349400, 724400, -1099400, -724400]`.

The public site exposes the full notice below through
`web/dashboard/static/dashboard/THIRD_PARTY_NOTICES.txt`.

No RNZ01 administrative proxy, authentication, password storage, kick/ban,
announcement, save, shutdown, restart, chat or raw console code is included.
No additional Palworld artwork, Gridcn components or npm dependencies were
copied during this integration.

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

The RNZ01 MIT License covers RNZ01's software contributions. It does not grant
rights to Palworld artwork, trademarks or other material owned by Pocketpair,
Inc. The map image appears to originate from Palworld game data. Palworld and
the map artwork are trademarks and copyrighted material of Pocketpair, Inc.
This project is an unofficial community dashboard and is not affiliated with
or endorsed by Pocketpair. Anyone redistributing the map must independently
verify that the intended use complies with applicable Pocketpair terms and
fan-content rules.
