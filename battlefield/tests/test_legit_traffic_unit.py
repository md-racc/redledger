"""Unit: legit-traffic schedules for the false-positive bait (no database)."""

from __future__ import annotations

from app.orchestrator import legit_traffic as lt


def test_one_bank_change_and_one_new_vendor_per_window() -> None:
    for seed in (1, 7, 42, 1234):
        for window, scheduled in ((lt.BANK_CHANGE_WINDOW, lt.bank_change_scheduled), (lt.NEW_VENDOR_WINDOW, lt.new_vendor_scheduled)):
            for start in range(0, 60, window):
                assert sum(scheduled(seed, d) for d in range(start, start + window)) == 1


def test_schedules_are_deterministic_and_seeded() -> None:
    days = range(40)
    for scheduled in (lt.bank_change_scheduled, lt.new_vendor_scheduled):
        assert [scheduled(42, d) for d in days] == [scheduled(42, d) for d in days]
        assert len({tuple(scheduled(seed, d) for d in days) for seed in range(20)}) > 1  # the seed moves the days
    assert not lt.bank_change_scheduled(42, -1) and not lt.new_vendor_scheduled(42, -5)  # never in seeded history


def test_first_invoice_delay_is_deterministic_and_bounded() -> None:
    delays = [lt.first_invoice_delay(42, d) for d in range(50)]
    assert delays == [lt.first_invoice_delay(42, d) for d in range(50)]
    assert set(delays) == set(range(1, lt.FIRST_INVOICE_MAX_DELAY + 1))
    assert lt.FIRST_INVOICE_MAX_DELAY < 7  # the first invoice must land inside the vendor-age < 7d window


def test_rng_streams_are_independent_per_purpose() -> None:
    a = lt._rng(42, 3, "bank_change").random()
    assert a == lt._rng(42, 3, "bank_change").random()
    assert a != lt._rng(42, 3, "new_vendor").random() and a != lt._rng(42, 4, "bank_change").random()


def test_invoice_prefix_from_vendor_name() -> None:
    assert lt._initials("Smith, Jones and Brown") == "SJA"
    assert lt._initials("Garcia-Lopez LLC") == "GLL"
    assert lt._initials("") == "VND"
