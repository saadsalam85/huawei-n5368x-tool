# Contributing

Thanks for wanting to make the tool better. It's a single-file Tkinter app,
so the bar to contributing is low — most work is: find a Huawei quirk, fix it,
prove it against the router, PR.

## Ways to help

### Report issues

Open an issue with:

- your router **model** and **firmware version** (Info tab shows it),
- the exact **Log tab** lines around the problem,
- what firmware/ISP you're on — quirks here are extremely carrier-specific.

Include a scan/sweep log if it's about bands or antennas; they are not
sensitive (no SIM/MSISDN in the logs).

### Test on another device

The only fully verified target is the **N5368X on firmware
10.0.5.2(H1SP8C1228)**. Results on:

- other N5368X firmware revisions,
- other N5x8x / B-series / other-ISP routers,

are genuinely valuable. Even a "works, with these differences" report helps
sharpen the quirks documentation. Report in an issue tagged `hardware`.

### Add screenshots

Follow [docs/SCREENSHOTS.md](SCREENSHOTS.md) — blur anything personal.

### Code

1. Fork the repo.
2. Create a branch: `git checkout -b your-change`.
3. Make the change in `huawei_tool.py` (keep it one file — that's the design).
4. Verify locally:
   - `python -m py_compile huawei_tool.py` — syntax.
   - Import the module headlessly (`python -c "import huawei_tool"`) — wires up.
   - Live-verify against your router. The project's testing convention is
     **live verification** (it talks to a real router; there is no unit-test
     suite because the interesting behaviour only exists on the hardware).
   - For GUI changes, drive the real Tk mainloop in a smoke script and confirm
     no UI freeze during long actions, and every long action has a progress bar.
5. Commit with a clear message (see style below).
6. Open a PR against `main` and link the issue it fixes.

## Code style

- Keep everything in `huawei_tool.py` — no new files for features.
- Match the existing style: tab-indented, section banners in comments, Chinese-
  style separator lines, methods grouped under `# ── Tab: ...` banners.
- No comments unless they explain *why* (especially firmware quirks — those
  comments are mini-docs).
- Every decision path must use **measured download speed** as the only metric.
  Never introduce a SINR/RSRQ tie-break into a scoring decision.

## Important: keep the quirks real

The firmware quirks documented in README/docs were discovered live against
hardware. If you "fix" them, be sure you test against the router before
claiming it — this device family has a long history of resetting opinions to
what the datasheet says, and then blaming the tool.

## Commit message style

Simple and specific. Examples:

```
sweep: measure DL after capture window so in-window probes aren't starved

fix: restore auto antenna mode after combo sweep (firmware wedge workaround)

docs: document B28 no-internet trap and DL-only scoring
```

## Releases

Maintainers tag versions from `CHANGELOG.md`. v1.0.0 is the baseline release;
feature additions bump the minor, bug fixes the patch.

## License

By contributing you agree your contributions are licensed under the same MIT
license as the project.