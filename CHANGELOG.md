# Changelog

All notable changes are tracked here. The project follows semantic-ish
versioning: features bump the minor, fixes bump the patch.

## [1.0.0] — 2026-09-26

First public release. Everything in the tool is available; behaviour is
firmware-verified against the N5368X on `10.0.5.2(H1SP8C1228)`.

### Added

- SCRAM login (base64+SHA256, session handling) with `huawei-lte-api` fallback.
- Band Lock: network mode / LTE band (hex mask + common-band picker) / 5G NR
  bands; Apply / Remove Lock / Restore Auto.
- Cell Scanner: modem tower search, per-cell EARFCN / PCI / RSRP / RSRQ / SINR,
  camped-cell highlight, click-to-lock.
- Network Search (public plmn list) and Re-register Auto.
- **Sweep All Bands** — per-band download measurement after a post-capture
  settle (probes run only when the modem's concurrent tower sweep has
  finished, so in-window starvation can't fake a 0 Mbps reading), ranked
  summary, auto restored at the end.
- **Auto Optimise Bands** — download-speed-only scoring; applies the best band
  only if its DL is above zero, otherwise leaves bands auto.
- **Antenna Combo Sweep** (combos 1–10) — DL measurement per combo with a
  stability soak (CQI + DL MCS gate), ranking, always returns to antenna auto
  (works around the firmware's fixed-combo wedge bug).
- Fast.com speed test with **server-node pruning** (probe targets, keep the
  reliably-fast survivors; best always kept, others at >=0.3x of best).
  OpenSpeedTest / speedtest.net fallbacks. Optional `speedtest-cli` detected.
- Signal dashboard: RSRP/RSRQ/SINR/CQI/MCS + rolling history graph.
- SMS, hosts, device/network info, timestamped coloured Log tab.
- **Progress bars and running-button states on every long action** — the UI
  never freezes during sweeps, searches, or speed tests.
- Two-row toolbar so every button stays reachable in a windowed (non-maximised)
  window.
- Full documentation: INSTALLATION, USAGE, TROUBLESHOOTING, SCREENSHOTS,
  CONTRIBUTING, SUPPORT; gitignore for credentials/logs; MIT license.

### Known limitations

- SINR on `device/signal` is unreliable on this firmware; CQI + negotiated MCS
  are mapped instead, and download speed is the only decision metric.
- `net/cell_info` is a dead feed (`100003`); the scanner uses the plmn-list
  search.
- Single-file architecture by design (running through the web UI's quirks is
  the point; no packaging or install beyond `requests`).
- Firmware-specific; only the N5368X / 10.0.5.2 target is fully tested.