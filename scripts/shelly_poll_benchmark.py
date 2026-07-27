"""Shelly local-API polling-frequency benchmark.

Answers: how fast can we usefully poll a Shelly plug over its local HTTP API?
Two limits are measured per plug, by sweeping a ramp of target rates:

  * transport limit  — how fast we can issue sequential GETs before latency
    climbs or the device errors (timeouts / resets / non-200).
  * metering refresh — how often the sensor actually updates. Polling faster
    just returns duplicate readings. Estimated from the change cadence of the
    (power, voltage, current) tuple — mains-noise voltage jitter reveals the
    true re-sample rate even on an idle plug.

Read-only: it only GETs the status endpoint, never toggles the relay. It ramps
up and stops the sweep once a rate starts erroring, so it won't hammer a small
ESP32-class device into instability.

Usage (venv active):
    python scripts/shelly_poll_benchmark.py 192.168.1.17 192.168.1.177 \
        --csv results/shelly_bench.csv
    python scripts/shelly_poll_benchmark.py 192.168.1.17 --rates 1,5,10,20 --window 10
    python scripts/shelly_poll_benchmark.py 192.168.1.17 --fresh-conn   # no keep-alive

Reuses ShellyDevice.connect() for the persistent aiohttp session and the
auto-detected endpoint (Switch / PM1 / Gen1 meter), so there's no endpoint logic
duplicated here. It does read the device's private attrs (_gen/_meter/_session/
_ip/_auth) — acceptable for a characterisation script.
"""

import argparse
import asyncio
import csv
import math
import os
import statistics
import sys
from collections import namedtuple
from pathlib import Path

# Run straight from a checkout without an editable install, matching the other
# scripts in this folder.
_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import aiohttp  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from lem.devices.shelly import ShellyDevice  # noqa: E402

DEFAULT_RATES = [1, 2, 5, 10, 20, 33, 50, 100]
DEFAULT_WINDOW = 15.0
ERROR_STOP_PCT = 5.0  # stop the ramp once a rate exceeds this error rate
READ_TIMEOUT = 5.0

Reading = namedtuple("Reading", "t latency ok value voltage current err")


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested without hardware)
# --------------------------------------------------------------------------- #

def percentile(sorted_vals: list[float], p: float):
    """Linear-interpolation percentile of an already-sorted list."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


def summarize(target_hz: float, window: float, samples: list[Reading]) -> dict:
    """Per-rate stats from raw Readings. Pure — no I/O."""
    n = len(samples)
    oks = [s for s in samples if s.ok]
    errs = n - len(oks)
    lat_ms = sorted(s.latency * 1000.0 for s in oks)

    # Freshness: count how often the (value, voltage, current) tuple changes.
    changes, prev = 0, None
    for s in oks:
        cur = (s.value, s.voltage, s.current)
        if prev is not None and cur != prev:
            changes += 1
        prev = cur

    return {
        "target_hz": target_hz,
        "achieved_hz": len(oks) / window if window else 0.0,
        "n": n,
        "errors": errs,
        "err_pct": (100.0 * errs / n) if n else 0.0,
        "lat_min": lat_ms[0] if lat_ms else None,
        "lat_mean": statistics.fmean(lat_ms) if lat_ms else None,
        "lat_p50": percentile(lat_ms, 50),
        "lat_p95": percentile(lat_ms, 95),
        "lat_max": lat_ms[-1] if lat_ms else None,
        "fresh_hz": changes / window if window else 0.0,
    }


def recommend(rows: list[dict]) -> dict:
    """Derive headline numbers from the per-rate summaries."""
    clean = [r for r in rows if r["err_pct"] <= ERROR_STOP_PCT]
    # Transport: highest target rate that stayed error-free AND kept up (achieved
    # within 10% of target).
    kept_up = [r for r in clean if r["achieved_hz"] >= 0.9 * r["target_hz"]]
    transport_hz = max((r["target_hz"] for r in kept_up), default=None)
    # Metering refresh: the plateau of fresh_hz (best estimate of true update
    # rate — stays flat once we poll faster than the sensor updates).
    refresh_hz = max((r["fresh_hz"] for r in rows), default=0.0)
    return {"transport_hz": transport_hz, "refresh_hz": refresh_hz}


# --------------------------------------------------------------------------- #
# Async benchmark
# --------------------------------------------------------------------------- #

def _meter_url(dev: ShellyDevice) -> tuple[str, str]:
    if dev._gen == 2:
        path, field = dev._meter
        return f"http://{dev._ip}/rpc/{path}", field
    return f"http://{dev._ip}/meter/0", "power"


async def _read_once(session, url, field, auth, fresh_conn) -> Reading:
    loop = asyncio.get_running_loop()
    timeout = aiohttp.ClientTimeout(total=READ_TIMEOUT)
    t0 = loop.time()
    try:
        if fresh_conn:
            async with aiohttp.ClientSession() as s, \
                    s.get(url, auth=auth, timeout=timeout) as r:
                r.raise_for_status()
                data = await r.json(content_type=None)
        else:
            async with session.get(url, auth=auth, timeout=timeout) as r:
                r.raise_for_status()
                data = await r.json(content_type=None)
        lat = loop.time() - t0
        return Reading(t0, lat, True, data.get(field),
                       data.get("voltage"), data.get("current"), None)
    except Exception as e:
        return Reading(t0, loop.time() - t0, False, None, None, None,
                       type(e).__name__)


async def _sweep_rate(dev, url, field, rate, window, fresh_conn) -> list[Reading]:
    """Poll one plug at a fixed target rate for `window` seconds, drift-free
    (mirrors runner.poll_plug: anchor + interval, realign if behind)."""
    interval = 1.0 / rate
    loop = asyncio.get_running_loop()
    end = loop.time() + window
    next_tick = loop.time()
    out = []
    while loop.time() < end:
        out.append(await _read_once(dev._session, url, field, dev._auth, fresh_conn))
        next_tick += interval
        delay = next_tick - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            next_tick = loop.time()  # fell behind; realign
    return out


async def benchmark_plug(ip, rates, window, fresh_conn, console) -> tuple[list[dict], list]:
    dev = ShellyDevice()
    console.print(f"\n[bold]● {ip}[/bold] — connecting…")
    await dev.connect(ip)
    url, field = _meter_url(dev)
    kind = "Gen1 /meter/0" if dev._gen != 2 else dev._meter[0]
    console.print(f"  endpoint: [cyan]{kind}[/cyan] (field '{field}'), "
                  f"keep-alive={'off' if fresh_conn else 'on'}")

    rows, raw = [], []
    try:
        for rate in rates:
            console.print(f"  sweeping {rate:>4} Hz for {window:.0f}s…", end="")
            samples = await _sweep_rate(dev, url, field, rate, window, fresh_conn)
            row = summarize(rate, window, samples)
            rows.append(row)
            for s in samples:
                raw.append((ip, rate, f"{s.t:.4f}", f"{s.latency*1000:.2f}",
                            int(s.ok), s.value, s.voltage, s.current, s.err or ""))
            console.print(f" achieved {row['achieved_hz']:.1f} Hz, "
                          f"{row['err_pct']:.0f}% err, p95 "
                          f"{row['lat_p95']:.0f} ms, fresh {row['fresh_hz']:.1f} Hz")
            if row["err_pct"] > ERROR_STOP_PCT:
                console.print(f"  [yellow]stopping ramp — {rate} Hz exceeded "
                              f"{ERROR_STOP_PCT:.0f}% errors[/yellow]")
                break
    finally:
        await dev.disconnect()
    return rows, raw


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def print_table(ip, rows, console):
    t = Table(title=f"{ip} — poll-rate sweep", header_style="bold")
    for c in ("target Hz", "achieved Hz", "err %", "p50 ms", "p95 ms",
              "max ms", "fresh Hz"):
        t.add_column(c, justify="right")
    for r in rows:
        t.add_row(
            f"{r['target_hz']:g}", f"{r['achieved_hz']:.1f}", f"{r['err_pct']:.0f}",
            _ms(r["lat_p50"]), _ms(r["lat_p95"]), _ms(r["lat_max"]),
            f"{r['fresh_hz']:.2f}",
        )
    console.print(t)
    rec = recommend(rows)
    thz = f"{rec['transport_hz']:g} Hz" if rec["transport_hz"] else "n/a"
    rhz = rec["refresh_hz"]
    floor = f"{1.0 / rhz:.2f} s" if rhz > 0 else "n/a"
    console.print(
        f"  → max reliable transport ≈ [green]{thz}[/green]; "
        f"metering refresh ≈ [green]{rhz:.2f} Hz[/green]; "
        f"suggested LEM --interval floor ≈ [green]{floor}[/green]"
    )


def _ms(v):
    return "-" if v is None else f"{v:.0f}"


def write_csv(path: Path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ip", "target_hz", "t_mono", "latency_ms", "ok",
                    "value", "voltage", "current", "error"])
        w.writerows(raw)


# --------------------------------------------------------------------------- #

async def main_async(args, console):
    rates = [float(x) for x in args.rates.split(",") if x.strip()]
    all_raw = []
    for ip in args.ips:
        try:
            rows, raw = await benchmark_plug(ip, rates, args.window,
                                             args.fresh_conn, console)
        except Exception as e:
            console.print(f"[red]{ip}: {type(e).__name__}: {e}[/red]")
            continue
        print_table(ip, rows, console)
        all_raw.extend(raw)
    if args.csv and all_raw:
        write_csv(Path(args.csv), all_raw)
        console.print(f"\nRaw samples → {args.csv} ({len(all_raw)} rows)")


def build_parser():
    p = argparse.ArgumentParser(description="Benchmark Shelly local-API poll rate.")
    p.add_argument("ips", nargs="+", metavar="IP", help="Shelly IP(s) to benchmark")
    p.add_argument("--rates", default=",".join(str(r) for r in DEFAULT_RATES),
                   help="comma-separated target rates in Hz")
    p.add_argument("--window", type=float, default=DEFAULT_WINDOW,
                   help="seconds to hold each rate (default 15)")
    p.add_argument("--csv", help="write raw per-sample rows here")
    p.add_argument("--fresh-conn", action="store_true",
                   help="new connection per request (contrast vs keep-alive)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()
    try:
        asyncio.run(main_async(args, console))
    except KeyboardInterrupt:
        console.print("\nAborted.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
