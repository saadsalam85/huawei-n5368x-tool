# User Manual

How to use every screen and every button. The app has header controls, a
signal/connection dashboard, and a row of tabs for the rest. **Every
long-running action shows a progress bar** — if you don't see one, nothing is
running.

> Golden rule of this tool: **download speed is the only metric that decides
> anything.** Signal numbers are shown to you, but sweeps and optimisers trust
> real DL Mbps only. This is deliberate — see Known quirks in the README.

## 1. Header (always visible)

| Control | What it does |
|---|---|
| Router IP | IP of the router. Default `192.168.8.1` |
| Password | Router admin password (the one used on the router's web UI) |
| Remember | Save login to local `huawei_config.json` |
| Connect / Disconnect | Login (SCRAM) and open the session, or close it |
| Status area | Green "Connected" + live band/PCI/CQI/MCS; red/grey when not |
| Progress strip | Global progress bar + current action label (always visible) |
| Log toggle | Opens/closes the live log panel under the header |

The connection badge also shows current band, PCI, RSRP/RSRQ and CQI/MCS
refreshed every few seconds while connected.

## 2. Dashboard tab

Live card grid: band / EARFCN / PCI, RSRP, RSRQ, CQI, negotiated DL MCS, and
upload/download rates. The two dense gauges are:

- **CQI / MCS** — the truthful signal axis on this firmware (SINR is not).
- **Signal history** — rolling graph of RSRP / RSRQ / SINR over the last ~120
  samples so you can watch a re-tune or sweep settle.

## 3. Cell Scanner tab

The heart of the tool.

| Button | What it does |
|---|---|
| **Scan** | Triggers the modem's tower search and lists every visible cell |
| **Network Search** | Full public-plmn network search (shows your carrier list) |
| **Sweep All Bands** | One pass over supported bands; DL-measures each; ranks; restores auto |
| **Speed Test** | Manual download + upload test (fast.com nodes pre-ranked) |
| **Copy Browser Neigh-Cell Snippet** | Copies the dev-page neighbour-cell snippet for pasting elsewhere |
| **Re-register Auto** | Re-applies full-auto registration after manual tests |
| **Remove Lock** | Clears any band/antenna lock you applied |

Columns shown per cell: **Band**, **EARFCN**, **PCI**, **RSRP**, **RSRQ**,
**SINR**, and a badge for the **camped** cell. Double-click/click a cell's band
to lock just that band.

**Manual band lock:** enter EARFCN/PCI in the side panel and press Apply — the
lock persists across reboots. Remove Lock returns to auto.

## 4. Bands tab

Full band-lock control:

- **Network Mode** — Auto / 4G only / 5G only / 4G+5G.
- **LTE Band** — hex mask of allowed LTE bands, plus a picker of common bands
  (B1, B3, B7, B8, B20, ...) as single locks.
- **5G NR Band** — NR band selection where supported.
- **Apply** sends the config (the lock persists), **Restore Auto** / **Remove
  Lock** returns to the router defaults.

## 5. Optimiser tab

- **Auto Optimise Bands** — runs each candidate band (or the current one),
  measures DL Mbps after a settle period, applies the fastest **if its DL is
  above zero**, otherwise logs "bands left auto". Table columns:
  **Band | PCI | DL Mbps** — the DL Mbps column is the score.
- **Sweep Antenna Combos (1–10)** — steps the antenna switch over all combos,
  soaks out the re-tune swing, DL-measures each, reports a ranking, then
  restores **auto** (the firmware can wedge on fixed combos; auto is the safe
  resting state).
- **DL probe health** — the table shows a red `0 / err` row for any band that
  camps but carries no data, so you can see the "great signal, no internet"
  traps this firmware sets.

## 6. SMS tab

List / read / send SMS through the router. The router's message settings apply.

## 7. Hosts / Info tab

- Manage the router's hosts / filter list.
- Pull device identity, firmware version, and network info into the log.

## 8. Log tab

Timestamped, coloured log of every action the tool takes: logins, session
checks, lock applies and their codes, sweep steps with per-band DL Mbps, speed
test results, and error conditions. This is where you read the **real story**
(curl-level reasons) instead of the pretty UI summary.

## 9. Workflows

### Find your best band automatically

1. Connect.
2. Cell Scanner → **Sweep All Bands**. Wait for the per-band progress.
3. Read the summary: `Download speed: B1 = 46.7 Mbps, B3 = 31.2 Mbps ...`
4. Bands better than your current one come with a suggested lock; or use
   **Auto Optimise Bands** to apply the winner yourself.

### Optimise just the antenna

1. Connect, leave authentication and band settings as-is (auto).
2. Optimiser → **Sweep Antenna Combos**.
3. Read the combo ranking after it finishes; antennas are left in **auto**.

### Manual full test (e.g. before/after a move)

1. Connect → Cell Scanner → **Speed Test** (note the DL/UL result in the log).
2. Check the Signal tab's CQI/MCS graph to see what really changed.

## 10. What "auto" means

- **Band auto** = `NetworkMode '00'`, the factory LTE band mask, no locks —
  the modem picks freely.
- **Antenna auto** = `SelectMode 0`, all ports in use.

The tool's philosophy: it *measures* for you and recommends, but it never
leaves a lock applied after a sweep unless you ask it to (Auto Optimise
explicitly applies its single best band). Remove Lock / Re-register Auto
returns to factory auto at any time.

## 11. Interpreting results

- **DL Mbps is the score.** 40+ Mbps here is a healthy single-node fast.com
  number; 0 on a camped cell means *no data on that cell*, no matter how the
  signal reads.
- Sweep values swing for a few seconds after a band/antenna change — the tool
  waits for settle so the numbers you read are post-tuning.
- Different fast.com sessions draw different server pools; node pruning keeps
  results comparable, but a fresh *Speed Test* button click may vary a few
  Mbps. Judge relative (B1 vs B3, combo 2 vs combo 9), not absolute.