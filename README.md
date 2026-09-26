# Huawei N5368X Router Tool

A desktop application for the Huawei **N5368X** 4G/5G home router (the classic
`192.168.8.1` gateway). It replaces the router's web UI for the things its
firmware hides or gets wrong: fine-grained band locking, a real cell scanner,
band/antenna optimisation driven by the thing that actually matters — **real
download speed** — plus a fast.com-based speed test, SMS and hosts management,
and a live signal dashboard.

Built and tested against firmware `10.0.5.2(H1SP8C1228)` on Windows.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8%2B-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows-informational.svg)
![Version](https://img.shields.io/badge/version-1.0.0-orange.svg)

---

## Why this tool exists

The N5368X web UI:

- has no way to lock a specific LTE band cleanly across reboots;
- hides the neighbour-cell list behind a development-only page;
- doesn't expose a real band/antenna sweep;
- reports **misleading signal numbers** on this firmware (see
  [Known firmware quirks](#known-firmware-quirks) — SINR is not trustworthy,
  RSRP is frozen, and some cells lock with a great signal and *no internet*).

This tool gives you a single window to do all of it, and uses **measured
download speed** as the only decision metric for every optimisation step —
because a "good" SINR/RSRP reading means nothing if the cell doesn't carry data.

## Features

- **SCRAM authentication** — base64+SHA256 login with session handling
  (huawei-lte-api fallback if installed).
- **Band Lock** — pick network mode (auto / 4G / 5G), LTE band, and 5G NR band;
  apply, or remove the lock to return to full auto.
- **Cell Scanner** — trigger the modem's tower search and read every visible
  cell (EARFCN, PCI, RSRP, RSRQ, SINR, band), with the currently camped cell
  highlighted. Click any locked/seen cell to sweep it.
- **Sweep All Bands** — step through every supported band, wait for each to
  camp, then measure **real download speed per band** after the modem settles;
  ranks results from best to worst and restores auto.
- **Auto Optimise Bands** — the same download-speed-only scoring, applied
  automatically, with a live progress bar.
- **Antenna Combo Sweep** — cycles antenna combos 1–10, soaks out the
  re-tuning swing, measures download speed per combo, and restores auto.
- **Speed Test** — download + upload via fast.com (server nodes are pre-ranked
  by measured throughput so dud nodes don't drag results down), with
  OpenSpeedTest / speedtest.net as fallbacks.
- **Signal dashboard** — live RSRP/RSRQ/SINR/CQI/MCS values plus a history
  graph, refresh timer, and full log view.
- **SMS, Hosts, Info, Logs** — read SMS, manage the hosts list, pull device and
  network info, and follow every action in a timestamped log tab.
- **Progress bars everywhere** — every long-running action (sweeps, searches,
  speed tests, network registration) has its own progress indicator, so the UI
  never looks frozen.

## Requirements

- Windows 10/11 (Tkinter GUI)
- Python **3.8+** (Tkinter ships with the standard Windows installer)
- `requests` — the only hard dependency
- Optional, auto-detected:
  - `speedtest-cli` — enables the speedtest.net fallback source
  - `huawei-lte-api` — enables the documented-library auth fallback

## Installation

```
pip install requests                # required
pip install speedtest-cli           # optional
pip install huawei-lte-api          # optional
```

Then either run it straight from the copy you already have, or clone:

```
git clone https://github.com/saadsalam85/huawei-n5368x-tool.git
cd huawei-n5368x-tool
python huawei_tool.py
```

Full step-by-step (including GitHub Desktop / portable-Python users):
**[docs/INSTALLATION.md](docs/INSTALLATION.md)**

## Quick start

1. Launch `python huawei_tool.py`.
2. Enter the router IP (default `192.168.8.1`), the admin password, tick
   *Remember*, and click **Connect** — you do not need to fill anything about
   this tool on the router side.
3. Open the **Cell Scanner** tab and click `Scan` to see what your area offers.
4. Use `Sweep All Bands` to find the fastest real band, or `Sweep Antenna
   Combos` in the Optimiser tab to tune the antenna ports.
5. Watch the results column — **download Mbps is the score** everywhere.

User manual with every tab and every button explained:
**[docs/USAGE.md](docs/USAGE.md)**

Something not working? **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**
covers logins, sweep refusals, no-internet-after-lock, slow results and more.

## How it measures speed

- The primary source is **fast.com**. Because its server pool is redrawn per
  session and includes unreachable nodes, the tool first *probes* the targets
  briefly, keeps the reliably fast ones (best always kept, others kept if at
  least 0.3x of best), then runs the timed download against the survivors.
- **Download rate is the only decision metric.** Band optimiser, band sweep,
  and antenna sweep all score purely on measured DL Mbps. Upload and signal
  numbers are shown for information but never vote.
- After any band or antenna apply, the modem re-tunes and readings swing — the
  tool waits for the modem to settle (soak period + stability gate) before it
  trusts a measurement.

## Known firmware quirks

These are deliberately documented so you don't chase ghosts:

- `device/signal` **SINR is unreliable** on this firmware (can report ~3–7 dB
  while the modem is negotiating 256QAM at MCS 21–31, CQI 11–15). Trust **CQI
  + negotiated MCS**, not SINR.
- `device/signal` RSRP is frozen (~ -80/-81 dBm); RSRQ is real.
- `net/cell_info` returns `100003` constantly (dead feed) — excluded.
- Some cells (e.g. B28 in our test area) lock with a *clean* SINR but deliver
  **no internet**. This is exactly why download speed is the only metric that
  decides anything.
- Band cells B32/40/41/42 return lock code `112003` on this firmware (refused);
  the sweep logs this and moves on — it's harmless.
- After a *fixed* antenna combo is applied, the firmware can wedge
  (`antenna-select-result` code 9) and refuse a new auto-scan until reboot.
  The tool leaves antennas in **auto** and warns when a wedge is detected.

## Privacy & security

- Credentials: you enter the router **admin** password; the tool saves it
  locally to `huawei_config.json` next to the script when *Remember* is ticked.
  That file is **gitignored** and never committed. Untick *Remember* and no
  password is stored at all.
- The scan and log features write results to `neighbour_log.txt` locally —
  also gitignored.
- The fast.com token embedded in the source is the public token from
  fast.com's own client script, not a secret.
- Only the router at the IP you enter is ever contacted — no telemetry, no
  external calls other than the speed-test servers you initiate.

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#privacy) for how to fully
wipe stored credentials.

## Screenshots

See [docs/SCREENSHOTS.md](docs/SCREENSHOTS.md) — contributions are welcome.

## Supporting the project

This tool is free and open source. If it saves you time, money, or sanity and
you'd like to say thanks, donations keep the project going (test devices,
carrier plans for sweep validation, and coffee for the maintainer):

- **USDT (TRC20):** `TJPjCe8NnEgm6SmFTVfBEB57A5FdHtSU1M` (TRON network only)

Full details (network warnings, sponsor recognition, other options):
**[docs/SUPPORT.md](docs/SUPPORT.md)**

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Contributing

Found a bug, own a different Huawei model, or want a feature?
[CONTRIBUTING.md](CONTRIBUTING.md) — pull requests welcome. If you test on
other firmware versions, please report your results; quirks are firmware- and
carrier-specific and that data makes the tool better for everyone.

## License

MIT — see [LICENSE](LICENSE).