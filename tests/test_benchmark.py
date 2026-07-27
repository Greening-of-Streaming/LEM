import importlib.util
import os

# The benchmark lives in scripts/, not the package — load it directly.
_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "scripts", "shelly_poll_benchmark.py")
_spec = importlib.util.spec_from_file_location("shelly_poll_benchmark", _PATH)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)

Reading = bench.Reading


def _ok(value, voltage=236.0, current=0.1, latency=0.01):
    return Reading(0.0, latency, True, value, voltage, current, None)


def _err():
    return Reading(0.0, 5.0, False, None, None, None, "TimeoutError")


def test_percentile_interpolates():
    assert bench.percentile([], 50) is None
    assert bench.percentile([7], 95) == 7
    assert bench.percentile([0, 10], 50) == 5
    assert bench.percentile([0, 10], 95) == 9.5
    assert bench.percentile([1, 2, 3, 4], 50) == 2.5


def test_summarize_counts_errors_and_rate():
    samples = [_ok(1.0), _ok(1.0), _err(), _ok(1.0)]
    s = bench.summarize(target_hz=10, window=2.0, samples=samples)
    assert s["n"] == 4 and s["errors"] == 1
    assert s["err_pct"] == 25.0
    assert s["achieved_hz"] == 1.5          # 3 ok reads over a 2s window
    assert s["lat_max"] == 10.0             # ms; error's 5s latency is excluded


def test_summarize_freshness_change_cadence():
    # Reading changes twice across the window -> fresh_hz = 2 / window.
    samples = [_ok(1.0), _ok(1.0), _ok(2.0), _ok(2.0), _ok(3.0)]
    s = bench.summarize(target_hz=50, window=1.0, samples=samples)
    assert s["fresh_hz"] == 2.0
    # All-identical readings (polling faster than the sensor updates) -> 0 fresh.
    flat = [_ok(5.0), _ok(5.0), _ok(5.0)]
    assert bench.summarize(1, 1.0, flat)["fresh_hz"] == 0.0


def test_recommend_transport_and_refresh():
    rows = [
        {"target_hz": 1, "achieved_hz": 1.0, "err_pct": 0.0, "fresh_hz": 1.0},
        {"target_hz": 10, "achieved_hz": 9.8, "err_pct": 0.0, "fresh_hz": 1.0},
        {"target_hz": 50, "achieved_hz": 30.0, "err_pct": 0.0, "fresh_hz": 1.0},  # can't keep up
        {"target_hz": 100, "achieved_hz": 20.0, "err_pct": 40.0, "fresh_hz": 1.0},  # errors
    ]
    rec = bench.recommend(rows)
    assert rec["transport_hz"] == 10        # highest error-free rate that kept up
    assert rec["refresh_hz"] == 1.0
