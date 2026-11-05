# Reverse-engineering notes

Evidence behind the design of FREQUENZ. Everything here was checked with real
tool output on 2026-11-02. Observations, inferences and open questions are kept apart.

## 1. Reference and sources

The reference is the live web app at `https://radio.garden/?hl=sv` (release `48e1795d` when it was analysed).

A third-party Android APK supplied for this project was checked and is **not** Radio Garden. It is the Uptodown App Store client: file `uptodown-com.jonathanpuckey.radiogarden.apk`, 15,659,226 bytes, SHA-256 `d903bec98d76854baa279c81b97048273a7ffd506e2d421308efbb6e7bf66b76`, package `com.uptodown`, version 7.42. None of its 22,437 DEX classes has a name containing `radiogarden` or `jonathanpuckey`, and no `radio.garden` URL appears in any DEX file. The Uptodown ads and consent SDKs in that file were not reused. The APK is not part of this repository, and no design decision depends on it.

## 2. Analysis tools

REA's JavaScript analysis of the web bundle is partial (section 3). The Android analysis tools were unavailable here because the JADX MCP jar is not configured. They were not needed, because the APK is not Radio Garden.

## 3. Web reference bundle (release `48e1795d`)

Files analysed (saved from `https://radio.garden/?hl=sv`):
`index-CcJOVu-K.js` (427 KB), `index-legacy-sINPbp9_.js` (594 KB), `modules-2bll9wX6.js` (250 KB),
`globe-D8fFMwrt.js` (160 KB), `rolldown-runtime-BdekjxZ0.js`, `polyfills-legacy-Cbum96GH.js`, and the stylesheet `index-YSey3RuP.css` (142 KB).

**REA result** (`analyze_javascript_application`, directory format):
- 7 relevant files, 6 parsed, 0 parse failures, 314 findings, 1,440,980 bytes read.
- `modules-2bll9wX6.js` **skipped**: "Owned JavaScript worker exhausted its heap". Re-running with
  `max_heap_mb: 4096` and a 900 s timeout gave the same result, so the limit is REA's per-file
  semantic budget, not the heap.
- Semantic unknowns: 51,878, including dynamic calls (11,555) and ambiguous object flow (6,910).
- `request` family: 0 retained relations. Fetch URLs are built dynamically, so REA could not
  attribute the endpoints. The endpoints below come from string search and live probing instead.

## 4. Public API (verified live)

Browser-style User-Agent required (plain `curl` gets HTTP 403). All responses are JSON
(`apiVersion`, `version`, `data`).

| Endpoint | Purpose | Verified |
|---|---|---|
| `GET /api/ara/content/places` | All places: `id`, `title`, `country`, `geo: [lng, lat]`, `size`, `boost`, `url`, sometimes `skipRide`. Version `d3519d0` at time of writing. 12,893 entries, 1.9 MB | yes |
| `GET /api/ara/content/places-core-columnar` | Compact columns (`ids`, `lngs`, `lats`, `sizes`, `boosts`) used by the web app | yes |
| `GET /api/ara/content/places-details-columnar` | Compact columns (`titles`, `countryIdx`, `countries`, `skipRides`) | yes |
| `GET /api/ara/content/page/{placeId}/channels` | "All stations" for a place: `content[].items[].page` with `type: channel` | yes |
| `GET /api/ara/content/page/{placeId}` | Place page (same items plus header) | yes |
| `GET /api/ara/content/channel/{stationId}` | Station detail: `website`, `social[]`, `place`, `country`, `preroll`, `stream`, `secure` | yes |
| `GET /api/ara/content/listen/{stationId}/channel.mp3` | **302** to the stream URL (`Location`); the web app uses `channel.${format ?? "mp3"}` | yes, for 8 stations on 7 hosts |
| `GET /api/ara/content/search?q=` | Search results (`content` blocks, with `locale` and `secure` in the bundle) | yes |
| `GET /api/ara/content/map` | Not an endpoint | 404 |

A station item looks like this (fields used by the app):
`{"type": "channel", "url": "/listen/{slug}/{stationId}", "title", "place": {"id", "title"}, "country": {"id", "title"}, "stream": "<host>", "secure": bool, "preroll": bool}`.
The station id is the last segment of `url`.

**Catalog size (final crawl).** All 12,893 places and 38,487 stations are stored. This equals
`sum(size)` over places, and every place's stored station count matches its API `size` (0 mismatches).
Stations with `preroll: true`: 1,864 (4.8 %). Boosted places: 243. Stations carry 229 distinct country names.

**Rate.** The crawl used four workers and a 0.1 s minimum interval between requests, at most about
10 requests per second. Throughput varied between about 1 and 6 places per second across runs. The
client retries 429 and 5xx responses with back-off and does not log those retries, so the cause of the
slow periods is not established. No place failed. A 30-request probe run during the slow start after a
restart returned only HTTP 200 (median latency 0.21 s).

## 5. Ads and monetisation in the web app

| Signal | Where | What it means for this client |
|---|---|---|
| `preroll: true` on stations | API `channel` items; the web bundle's track logic picks `!e.preroll` channels first (`Ne(a.filter(e=>!e.preroll))`) | About 4.5 % of stations, nearly all zeno.fm. The listen endpoint redirects to the direct stream, so the ad appears to be added client-side (inference). **Not implemented**: the app plays the direct stream. |
| Entitlements `remove_advertising` and `premium` | Web bundle customer-info handling (`updateCustomerInfo`) | Paid tiers. **Not implemented.** |
| Native-app promotions (`promotionContainer`, `NativeApp` components) | Web bundle CSS-module classes | Marketing banners. **Not implemented.** |
| `boost: true` (243 places) | Globe: boosted dots are drawn 1.5× (`boostScale`) when zoomed out | Visual emphasis from the API, **kept** as a size boost. |
| `preroll` playback path | Web bundle `track` function, `url: /listen/${id}/channel.${format}` | The app never requests any ad media. |

## 6. Globe constants taken from the web bundle

| Constant | Value | Use in this client |
|---|---|---|
| `smallPlaceScale` / `mediumPlaceScale` / `largePlaceScale` | 0.14 / 0.27 / 0.42 | Dot size classes (`PlaceSet.scale_classes`) |
| `mediumPlaceTreshold` / `largePlaceTreshold` | 5 / 20 stations | Thresholds (`size > 5`, `size > 20`) |
| `boostScale` | 1.5 | Boosted places |
| `globalScale` | 0.5 | Overall dot scale (absorbed into the base point size) |
| Brand blue | `#3b00ff` (globe chunk) | Inspired the ocean and land colours; the app's palette is its own |

The web globe draws raster map tiles. This client draws vector data from Natural Earth 1:10m (public
domain): land, lakes, glaciers, borders and rivers. The ocean is one colour because the 10 m depth bands
contain straight-line artifacts (see the README section "Globe and map data").

## 7. Playback verification

Headless playback with `fakesink` through the real listen redirect (`tests/e2e_gui_check.py` drives
the same code path in the window):

| Station | Host | Result |
|---|---|---|
| Asb24music (Villa de Mayo) | streamcasthd.com | playing, position 26 s after 12 s wall time |
| Radio Fantastica (pre-roll) | zeno.fm | playing, ICY titles "Pista 9", then "LA KONGA SIEMPRE…"; no ad |
| Several others (Paris area, Christchurch, Trujillo, Rengo, Vanderbilt) | various | playing; one dead station reconnects before playing |

## 8. What is still unknown

- Whether the Radio Garden Android app (not the Uptodown one) uses the same endpoints. The web is the reference.
- The exact rules for the `format` parameter on `listen` (every station in the sample returned `mp3`).
- Rate limits: throughput varied during the crawl. The client retries 429 and 5xx responses silently,
  so whether the server throttled during the slow periods is not established. No place failed.
