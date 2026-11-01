# Actual Sprint 2 recording

[Two-minute silent MP4](BBMS_Sprint2_Demo.mp4) — 1600×1000, 25fps, H.264,
120.00 seconds, no audio stream. The real browser source is 240.01 seconds with
one uniform 2.00008× speed multiplier; no section-specific acceleration.

Accounts and donor/bag values use Abhinav, Uttam, Navaneeth and Akshay. Grey
pointer-down indicators are recording-only decorations; there is no cursor,
caption bar, synthetic UI or fabricated outcome. Dropdowns are actually opened,
held visibly, and selected using the browser keyboard. The application itself
handles all forms, database writes, role changes, manifests, receipts and exports.

The final recording was made in an isolated headless Brave/Chromium 156 browser
against the real loopback Django server, after the native desktop tool repeatedly
interrupted URL verification. It uses a fresh synthetic SQLite fixture. Earlier
interrupted desktop clips are not included in the final MP4. The complete final
capture contains 59 checked steps, 1683 timestamped screencast frames and zero
browser JavaScript errors. Both exports were fully decoded to check corruption;
sampled exported frames were visually reviewed, including native dropdowns.
Chromium omits native picker surfaces from its event screencast; the encoder
preserves the actual same-session picker screenshots during their open intervals.
A read-only capture of the persisted delivery table also keeps the received rows
fully visible. These are real browser captures, not reconstructed screens.

| Approximate playback | Workflow |
| --- | --- |
| 0–30s | Running app, hospital login, group/component dropdowns, quantity/date/STAT and request submission. |
| 30–65s | Staff login, live STAT queue, approval, actual Bag ID cross-match, FEFO allocation and dispatch manifest. |
| 65–90s | Owning hospital tracks the dispatched bags and confirms receipt; Delivered state and receiver identity. |
| 90–108s | Admin component separation and source/child traceability. |
| 108–120s | Reports, actual CSV download and verified read-only central audit. |

Full step timings and video checksum are committed in
[`docs/sprint2/evidence`](../docs/sprint2/evidence/summary.json).

## Reproduce

Use a new empty synthetic database for the recording so Bag IDs are not already
allocated or separated. Do not delete or reuse a real database.

```text
python demo/run_sprint2.py --database ../bbms-sprint2-recording.sqlite3 --port 8774
```

In a second shell, install Playwright into a local Node tooling directory (it is
a recording dependency, not a production requirement), then make it resolvable
with `NODE_PATH`. Set `BBMS_BROWSER_PATH` to an installed Chromium-family browser
executable if the default Windows Brave path is not applicable. Run:

```text
python -m pip install -r demo/requirements.txt
node demo/record_sprint2.cjs ../sprint2-recording
python demo/encode_sprint2.py --recording ../sprint2-recording --ffmpeg /path/to/ffmpeg --output demo/BBMS_Sprint2_Demo.mp4 --normal-output ../BBMS_Sprint2_Normal_Speed.mp4
```

The capture saves real timestamped browser frames and checked screenshots. The
encoder preserves their timing and applies the same playback multiplier to all
frames. Keep frames, source recordings and local SQLite files outside Git. Only
the final MP4 and compact reproducibility/evidence files are uploaded here.

Use `demo/check_nfr.py` only with its separate server/database on port 8773;
it creates 50 synthetic accounts/sessions and ten real bookings. It must not
share the recording fixture or run against a production database.
