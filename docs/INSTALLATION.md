# Installation Guide

This guide covers everything from a fresh Windows PC to a running copy of the
tool. The tool only talks to your router on your LAN — nothing is installed on
the router itself.

## 1. What you need

| Requirement | Why | Notes |
|---|---|---|
| Windows 10 / 11 | The GUI uses Tkinter | Linux/macOS may work but the UI is untested there |
| Python 3.8+ | Runtime | **Must have Tcl/Tk** (included in the standard `python.org` installer) |
| `requests` | HTTP to the router | The only hard requirement |
| Router | Huawei N5368X at `192.168.8.1` | Other Huawei models may partially work; quirks differ |

## 2. Install Python

1. Download the installer from <https://www.python.org/downloads/>.
2. On the first installer screen, tick **"Add python.exe to PATH"**.
3. Choose *Install Now*.
4. Verify in a terminal:

```bat
python --version
```

> If you get `Python was not found`, the PATH box wasn't ticked. Re-run the
> installer, pick *Modify*, and tick "Add to PATH".

If you're completely new to Python, the *Microsoft Store* Python also works
with Tkinter included, but the manual installer from python.org is preferred.

## 3. Install the dependencies

Open a terminal (Start menu → type `cmd`, Enter) and run:

```bat
pip install requests
```

Optional extras (both are auto-detected and add fallback sources):

```bat
pip install speedtest-cli          :: extra speed-test source
pip install huawei-lte-api         :: documented-library login fallback
```

## 4. Get the tool

**Option A — GitHub Desktop (easiest for updates):**

1. <https://desktop.github.com/ → Download → install>.
2. Sign in with your GitHub account.
3. File → *Clone repository* → search `n5368x-huawei-tool` → choose a folder.
4. You now have a folder with `huawei_tool.py` in it.

**Option B — plain command line:**

```bat
git clone https://github.com/saadsalam85/huawei-n5368x-tool.git
cd huawei-n5368x-tool
```

**Option C — no git at all:**

Download <https://github.com/saadsalam85/huawei-n5368x-tool/archive/refs/heads/main.zip>,
unzip it. To update later you just download the zip again.

## 5. First launch

```bat
cd huawei-n5368x-tool
python huawei_tool.py
```

The window opens with the connection fields filled in:

- **Router IP** — `192.168.8.1` (the N5368X default).
- **Password** — the router's admin password (same one you use to log into
  its web UI at `http://192.168.8.1`).
- **Remember** — saved to the local `huawei_config.json`. Untick and nothing
  is stored; you'll be asked every launch.

Click **Connect**. The header turns green and live signal values appear.

## 6. Verify the install

Go to the **Cell Scanner** tab and press `Scan`. After ~10–30 seconds you'll
see a list of cells (EARFCN / PCI / RSRP / RSRQ / SINR) with your camped cell
highlighted. If that works, everything works — the hard parts (auth, dev-mode
session, tower search) are all proven by one successful scan.

## 7. Windows SmartScreen / firewall notes

- If Windows *SmartScreen* warns about `python.exe` or a downloaded zip, it's
  the generic "unknown app" prompt — choose *More info → Run anyway* for your
  own downloaded copy.
- If Windows Firewall asks about Python's network access, allow it **on
  private networks** so the tool can reach `192.168.8.1` and the speed test
  servers. Speed tests initiate outbound HTTPS connections to fast.com.

## 8. Updating

- GitHub Desktop: Fetch origin → Pull.
- CLI: `git pull`.
- Zip: re-download and overwrite `huawei_tool.py`.

Your saved login (`huawei_config.json`) and logs are never overwritten or
committed, so updates don't touch your settings.

## Next

Read [docs/USAGE.md](USAGE.md) for the full user manual.