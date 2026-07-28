# LEM — Local Energy Measurement

A lab tool to measure power consumption from one or more smart plugs on the LAN
(TP-Link Tapo P110 and Shelly plugs today; other plugs or PDUs are one module away). The local
companion to [REM](https://github.com/Greening-of-Streaming/rem) (Remote Energy Measurement).
Successor to [tapo_measure_tool](https://github.com/Quanteec/tapo_measure_tool)
and `dual_measure_tool` — no web server, one command (or one double-click).

- **Local by design** — plugs are measured over your LAN using the Tapo local
  protocol. **LEM never calls the TP-Link cloud API.**
- **Multiple plugs at once** — each polled concurrently at a drift-free interval.
- **Crash-safe** — every sample is flushed to disk as it arrives. Ctrl-C stops
  gracefully with a summary; even `kill -9` loses at most the in-flight sample.
- **Live display** — per-plug power, sample count, and status (terminal or GUI).
- **REM-ready data** — watts at 3-decimal precision (lossless: the P110 reports
  integer mW), UTC ISO 8601 timestamps, and a combined CSV whose columns
  (`timestamp,alias,power_w`) map 1:1 to REM's `gos_rem(time, alias, power_watts)`
  table.

## Download (prebuilt apps)

Non-technical testers: grab the latest signed-later build from
**[Releases](https://github.com/Greening-of-Streaming/LEM/releases)** — `LEM-macos.zip`
(macOS) or `LEM-windows.zip` (Windows). No Python needed. (Unsigned for now,
so macOS/Windows will warn on first launch — right-click → Open / "Run anyway".)

## Install (CLI)

```sh
git clone https://github.com/Greening-of-Streaming/LEM.git && cd LEM
python3 -m venv venv && source venv/bin/activate
pip install -e .            # add '.[gui]' for the desktop app, '.[dev]' for pytest
cp config.example.toml config.toml   # or let 'lem --scan' create it
```

Requires Python ≥ 3.11.

## Use (CLI)

```sh
lem --scan                                # discover Tapo + Shelly plugs on the local /24 (Shelly needs no credentials)
lem --scan 10.0.0.0/24                    # ...or an explicit subnet
lem --list                                # show configured plugs
lem --rename shellyplug-abc "Living-room TV"   # give a plug a friendly name
lem --plugs desk,rack --duration 10m      # measure two plugs for 10 minutes
lem --all                                 # every configured plug
lem --plugs desk --interval 0.5 --duration unlimited   # until Ctrl-C
lem --plugs fake1 --duration 30s          # dry run, no hardware
```

Durations: bare seconds, `90s`, `10m`, `2h`, or `unlimited`. First Ctrl-C stops
gracefully (data is already on disk); a second one hard-exits.

`--scan` probes the subnet for hosts answering on port 80, then confirms each
one with a real Tapo handshake (needs your Tapo account login — from the
config, `TAPO_USERNAME`/`TAPO_PASSWORD`, or an interactive prompt; saved once a
scan succeeds). Each device found is offered interactively: accept or refuse,
and name it (the plug's Tapo nickname is the suggested alias). With existing
plugs configured you choose add-vs-replace up front; everything else in the
config file is preserved. By default the scan only offers devices that can
measure power (Tapo P110/P115 and Shelly); hubs, bulbs and basic plugs are
hidden — pass `--nofilter` (or tick "show all" in the GUI dialog) to include them.

**Renaming a plug.** Shelly plugs are discovered under their factory id (e.g.
`shellyplugpmg3-9070…`) because Shelly stores your app nickname in the cloud, not
on the device. Rename them right in LEM — no config editing, no device access:

```sh
lem --rename shellyplugpmg3-9070695b7c78 "Living-room TV"
```

In the desktop app, **double-click the plug** and type a name. For a Shelly the
name you give is the identity REM sees. (Tapo plugs keep their Tapo-app nickname,
since REM matches on it — rename those in the Tapo app and re-scan.)

Each run writes to `results/` (override with `--results-dir` / `--run-name`):

- `<run>_<alias>.csv` per plug — `timestamp,power_w`
- `<run>_combined.csv` — `timestamp,alias,power_w` (REM-shaped)

## Configuration

`config.toml` (gitignored — it holds credentials; see `config.example.toml`).
Searched in: `./config.toml`, `~/.config/lem/config.toml` (the GUI's default),
then the legacy `~/.config/measure/` path.

```toml
[defaults]
interval    = 2.0
duration    = "10m"
results_dir = "results"

[credentials.tapo]           # TAPO_USERNAME / TAPO_PASSWORD env vars override
username = "you@example.com"
password = "changeme"

[plugs.desk]
type = "tapo"
ip   = "192.168.1.41"
```

Any per-plug key besides `type`/`ip` is passed to the device driver — credential
overrides, the fake device's `fail_rate`, or (one day) a PDU's outlet number.

## Desktop app (GUI)

The same core with a point-and-click face, for testers who don't use terminals:

```sh
python3 -m venv venv && source venv/bin/activate   # if not already active
pip install -e '.[gui]'
lem-gui
```

Tick plugs, set duration/interval, Start/Stop, live table, network scan with an
accept/rename dialog (double-click a plug to rename later), and an "Open
results folder" button. CSV output is identical to the CLI's.

### Packaging (macOS)

```sh
./packaging/build_macos.sh     # -> dist/LEM.app (unsigned)
```

The same `packaging/lem.spec` builds the Windows .exe when run on a Windows
machine (PyInstaller doesn't cross-compile) — CI workflow to follow. Signing/
notarization steps are sketched in `packaging/build_macos.sh` and will be
enabled once the Greening of Streaming Apple Developer account is active.

## Sending data to REM

LEM can stream measurements into a [REM](https://github.com/Greening-of-Streaming/rem)
experiment while they run — the local companion to REM's cloud collector.
Identity is the plug's **Tapo nickname**, exactly what REM's collector uses, so
local and cloud data for the same plug merge automatically.

Your operator creates an experiment in REM and gives you a **join code**
(`REM1-…`). Then:

```sh
lem rem join REM1-xxxx…      # connect (also sets the measurement cadence)
lem --all --duration 30m     # measure — data streams to REM as it's captured
lem rem status               # connection + how much has been uploaded
lem rem sync                 # upload any runs that REM missed (offline catch-up)
lem rem leave                # disconnect
```

In the desktop app, the **Connect to REM…** button does the same: paste the
code, then the button shows the experiment name and each run streams up with a
live uploaded/behind counter.

Guarantees worth knowing:

- **Local by design.** Even when connected to REM, LEM measures plugs over the
  LAN and never calls the TP-Link cloud. While LEM is measuring a plug, REM
  pauses its own cloud polling of it (saving TP-Link API calls) and resumes
  automatically if LEM stops.
- **Nothing is lost.** The local CSV is the source of truth; a `.sync` sidecar
  tracks what REM has acknowledged. A network drop just delays upload — LEM
  catches up, and `lem rem sync` backfills whole runs measured offline.
- **REM sets the pace.** The experiment's cadence becomes LEM's sample interval
  (override with `--interval` if you must).

## Extending

- **New device type** (plug, PDU): add one module in `src/lem/devices/`
  implementing `BaseDevice` (`connect` / `get_power_mw` / `disconnect`) and
  register it in `DEVICE_TYPES` in `devices/__init__.py`. Nothing else changes.
- **New output** (e.g. pushing to REM): add a module in `src/lem/sinks/`
  implementing `BaseSink` (`open` / `write` / `close`) and append it to the sink
  list in `cli.py`. The measurement loop is sink-agnostic.

## Test

```sh
pytest                               # parsing/config/scan unit tests
lem --plugs fake1 --duration 10s     # end-to-end without hardware
QT_QPA_PLATFORM=offscreen python scripts/gui_smoke.py   # GUI end-to-end
```

The `fake` device type generates ~40 W synthetic data; give it `fail_rate = 0.5`
in config to exercise the retry/reconnect path.

### Shelly poll-rate benchmark

`scripts/shelly_poll_benchmark.py <ip>` sweeps polling rates against a Shelly's
local API and reports its transport limit and how often its sensor actually
updates (read-only; ramps up and backs off on errors). Measured on a Plug (PM)
G3: the API sustains ~18–20 Hz but the meter only refreshes **~1 Hz**, so
polling faster than ~1 Hz just returns duplicates — ~1–2 s is the sweet spot.
LEM therefore **floors the poll interval at 1 s for Shelly plugs** (`ShellyDevice.MIN_INTERVAL_S`).

**Shelly vs Tapo, measured:** the Shelly has **no temporal advantage** over the
TP-Link Tapo P110 — both usefully refresh about once a second — and a **power-
resolution disadvantage**: the P110 reports integer **milliwatts** (0.001 W),
while these Shelly plugs resolve only to ~**0.1 W** and read low single-watt
loads unreliably. Prefer a Tapo P110 for small/precise loads; the Shelly is a
fine no-cloud option for larger loads.
