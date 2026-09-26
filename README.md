# Huawei N5368X Router Tool

A desktop GUI tool for the Huawei **N5368X** 4G/5G router (`192.168.8.1` default).
Combines band/network controls, a live cell scanner, band optimiser, antenna-combo
sweeper, and speed-testing into one window. Built against firmware `10.0.5.2(H1SP8C1228)`.

## Features

- **SCRAM auth** — veryraregaming-style base64+SHA256 login (with `huawei-lte-api`
  fallback when installed), SCRAM-session handling, dev-mode `second_login`.
- **Band Lock** — select network mode / LTE band / 5G NR band, apply, remove lock.
- **Cell Scanner** — scan visible cells (EARFCN/PCI/RSRP/RSRQ/SINR) via the modem's
  plmn-list search; one row shows the currently camped cell; click a band to sweep.
- **Sweep All Bands** — measure real **download speed per band** (the only decision
  metric) after each band camps, rank results, restore auto.
- **Auto Optimise Bands** — same DL-only scoring, applies the best band automatically.
- **Antenna Combo Sweep** — cycles antenna combos 1-10, measures download speed per
  combo with a stability soak, leaves the best combo applied, then restores auto.
- **Speed Test** — fast.com-based (pruned to healthy server nodes), OpenSpeedTest /
  speedtest.net fallbacks, upload + download.
- **Signal dashboard** — RSRP/RSRQ/SINR/CQI/MCS history graph, SMS, hosts, info, logs.

## Screenshots / usage

1. `pip install -r requirements.txt`
2. `python huawei_tool.py`
3. Login with `admin` and the router's admin password (saved locally in
   `huawei_config.json` — gitignored).
4. The Cell Scanner tab has: `⟳ Scan`, `🔍 Network Search`, `🔭 Sweep All Bands`,
   `🔄 Speed Test`; band / antenna tuning lives in the Optimiser tab; the header
   strip has the connection fields.

## Requirements

- Windows (Tkinter GUI); Python 3.8+
- `requests` (only hard dependency)

Optional: `speedtest-cli`, `huawei-lte-api` — auto-detected, not required.

## Firmware quirks (known)

- `device/signal` **SINR is unreliable** on this firmware (reports 3-7 dB while the
  modem negotiates 256QAM MCS 21-31, CQI 11-15). **CQI + negotiated MCS are the
  truthful axis.**
- `device/signal` RSRP is frozen (~-80/-81); RSRQ is real.
- `net/cell_info` returns `100003` constantly (dead feed) — excluded.
- **Band locks that fail to connect** (e.g. B28 / EARFCN 9360 here) can camp with a
  clean SINR but deliver **no internet** — download-speed measurement is the only
  honest vote, which is why every decision path uses real DL throughput.
- Some band-lock codes (B32/40/41/42) return `112003` on this firmware (refused).
- With this firmware, band re-registration may need a few seconds to settle before
  speed results are trustworthy.

## Privacy

The tool stores your router's password in the local `huawei_config.json`. That file
is gitignored and should never be committed.

## License

MIT — see [LICENSE](LICENSE).