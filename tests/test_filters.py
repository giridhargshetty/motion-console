import random
import statistics

from pose_service.filters import OneEuroFilter

DT = 1 / 30  # camera rate


def run(f, values):
    return [f(v, i * DT) for i, v in enumerate(values)]


def test_first_sample_passes_through():
    assert OneEuroFilter()(0.42, 0.0) == 0.42


def test_constant_signal_stays_constant():
    out = run(OneEuroFilter(min_cutoff=1.0, beta=10.0), [0.5] * 60)
    assert all(abs(v - 0.5) < 1e-12 for v in out)


def test_reduces_jitter_when_still():
    rng = random.Random(0)
    noisy = [0.5 + rng.gauss(0, 0.01) for _ in range(300)]
    out = run(OneEuroFilter(min_cutoff=1.0, beta=0.0), noisy)
    assert statistics.stdev(out[30:]) < statistics.stdev(noisy[30:]) / 2


def test_beta_reduces_lag_on_fast_move():
    ramp = [i * 0.05 for i in range(30)]  # 1.5 screen units per second
    slow = run(OneEuroFilter(min_cutoff=1.0, beta=0.0), ramp)
    fast = run(OneEuroFilter(min_cutoff=1.0, beta=10.0), ramp)
    assert abs(ramp[-1] - fast[-1]) < abs(ramp[-1] - slow[-1]) / 2


def test_repeated_timestamp_is_ignored():
    f = OneEuroFilter()
    f(0.0, 0.0)
    f(1.0, 0.1)
    before = f(1.0, 0.2)
    assert f(99.0, 0.2) == before


def test_reset_starts_fresh():
    f = OneEuroFilter()
    f(0.0, 0.0)
    f.reset()
    assert f(0.8, 5.0) == 0.8
