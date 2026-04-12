import pytest
from vortex.observability.backoff import ExponentialBackoff


def test_backoff_grows_then_caps():
    b = ExponentialBackoff(initial=1.0, factor=2.0, cap=8.0, jitter=0.0)
    assert b.next() == 1.0
    assert b.next() == 2.0
    assert b.next() == 4.0
    assert b.next() == 8.0
    assert b.next() == 8.0  # capped


def test_backoff_reset():
    b = ExponentialBackoff(initial=1.0, factor=2.0, cap=10.0, jitter=0.0)
    for _ in range(5):
        b.next()
    assert b.current > 1.0
    b.reset()
    assert b.next() == 1.0


def test_backoff_jitter_within_bounds():
    b = ExponentialBackoff(initial=4.0, factor=2.0, cap=4.0, jitter=0.5)
    for _ in range(50):
        v = b.next()
        # full jitter samples uniformly from [0.5*4, 4]
        assert 2.0 <= v <= 4.0


def test_backoff_invalid_args():
    with pytest.raises(ValueError):
        ExponentialBackoff(initial=0.0)
    with pytest.raises(ValueError):
        ExponentialBackoff(factor=0.5)
    with pytest.raises(ValueError):
        ExponentialBackoff(initial=10.0, cap=5.0)
    with pytest.raises(ValueError):
        ExponentialBackoff(jitter=1.5)
