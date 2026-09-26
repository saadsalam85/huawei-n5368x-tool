# Troubleshooting

Real problems people hit, in order of likelihood. Read the **Log tab** first —
every answer below is visible there in plain text.

## 1. Can't connect / login fails

- Wrong password? The tool needs the **router admin** password, the same one
  the web UI at `http://192.168.8.1` accepts.
- Is the PC on the router's network? Check `ping 192.168.8.1`.
- Router IP changed? Update the IP field before connecting.
- The router may reject rapid repeat logins — wait a few seconds between
  attempts.
- Firmware differs from `10.0.5.2(H1SP8C1228)`? Auth is based on the standard
  Huawei login; most N5x8x family firmwares accept it. If yours refuses, install
  `huawei-lte-api` (`pip install huawei-lte-api`) which the tool uses as a
  fallback auth path.

## 2. Login works but Scan returns nothing / error

- The tower search needs a moment after connection. Wait ~5 s, scan again.
- Some firmware refuses a new scan right after a **fixed antenna apply** (code
  `antenna-select-result` = 9). Reboot the router, or use Re-register Auto to
  clear the wedge.
- `net/cell_info` reporting `100003` is a known dead feed on this firmware — the
  scanner intentionally uses the plmn-list search instead; don't chase 100003.

## 3. Sweep says lock code 112003 on some bands

Bands B32/40/41/42 are refused by this firmware (it doesn't support locking
them). The sweep logs `112003` and moves on — harmless. It just means that
particular band can't be locked by any tool on this firmware.

## 4. A band locks with a great signal but no internet

This is the firmware's favourite trap, seen clearly with **B28** / EARFCN 9360
in some areas: it camps with clean SINR and good RSRQ, but delivers **zero
data**. Symptoms:

- Sweep shows `DL=0 Mbps (no data)` for a green-signal row.
- Speed test reads 0 or near-0 even though the badge shows camped.

That band is unusable regardless of how the signal looks — **download Mbps is
the only honest vote**, which is exactly why the optimiser refuses to apply a
band whose DL is 0.

## 5. Speed test results look slow or inconsistent

- **fast.com redraws its server pool each session.** Some sessions draw
  unreachable/slow nodes (some regions serve ~0.6 Mbps, good ones 40–55).
  The tool pre-ranks nodes and keeps only the good ones — that's why numbers
  look higher and stabler than raw pooling.
- First sample right after a band/antenna change is post-re-tune — the tool
  soaks these out; a manual Speed Test right after an apply can still read low.
- Another device hammering the router's WiFi will share the pipe — test when
  the link is otherwise idle.
- Firewall blocking Python's outbound HTTPS would zero out the DL only — allow
  Python on **private** networks (see INSTALLATION).

## 6. After a fixed antenna combo, sweeps stop working until reboot

Known firmware bug: applying a fixed combo (`ActionMode != 0`) can wedge the
radio (`antenna-select-result` code 9) and a subsequent auto-scan is refused.
Mitigation built into the tool:

- Antenna sweeps **always end in auto** (SelectMode 0).
- A detected wedge is logged with a clear warning.
- If it happens anyway: reboot the router, or `📶 Re-register Auto` after
  boot clears it.

## 7. The signal bar lies (SINR, RSRP)

On this firmware:

- `device/signal` **SINR ranges ~3–7 dB even on a great link**; actual link
  quality is in **CQI (11–15) and DL MCS (21–31 / 256QAM)**. Judge by CQI+MCS.
- RSRP is frozen around ~ -80/-81 dBm and resists change. RSRQ is real.

Trust the CQI/MCS gauges and, above all, measured throughput.

## 8. UI: buttons cut off in a small window

The toolbar splits across two rows automatically (Scan / Network Search /
Sweep All Bands / Speed Test on the first; utilities on the second) and the
window enforces a minimum size, so every control stays reachable even windowed.
If a button still isn't visible, maximise or widen the window, or restart the
app (window geometry is remembered from the OS taskbar, not stored in the tool).

## 9. Where are my results?

- Per-band/antenna rankings are written to the **Log tab** during sweeps.
- Neighbour-cell scans are appended to `neighbour_log.txt` next to the script.
- Speed test results print to the Log tab and the global status.

## 10. Privacy — how to wipe stored credentials

1. In the app, just remove the tick from *Remember* and reconnect — nothing
   new is written.
2. To delete what's already stored, delete the local file
   `huawei_config.json` that sits next to `huawei_tool.py` (or edit it — it's
   plain JSON).
3. `neighbour_log.txt` contains scan data from your area — delete it too if
   you don't want it on disk.

The repo never contains any of these local files (they're gitignored).

## 11. Log says "session check failed" mid-use

The router drops idle sessions. The tool auto-relogs (it re-runs the SCRAM
login). If it fails to re-establish twice, log out of the router's web UI to
free another session slot, then reconnect.

## 12. Still stuck?

Open an issue at <https://github.com/saadsalam85/huawei-n5368x-tool/issues>
and paste:

- firmware version (Info tab),
- the exact Log tab lines around the failure,
- your model, and whether it's the same N5368X or something else
  (quirks are firmware- and carrier-specific — that data genuinely helps).