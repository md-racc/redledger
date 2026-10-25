"""The synthetic company's identity and its themed vendor roster (seed/company.py). No database."""

from __future__ import annotations

import random

from seed.company import CATEGORIES, COMPANY, KINDS, line_item, vendor_kind, vendor_name


def _roster(seed: int, n: int = 60) -> list[tuple[str, str]]:
    rng, names, taken, out = random.Random(seed), random.Random(f"company:{seed}:vendor_names"), set(), []
    for _ in range(n):
        cat = rng.choice(CATEGORIES)
        name = vendor_name(names, cat, taken)
        taken.add(name)
        out.append((cat, name))
    return out


def test_company_identity() -> None:
    assert COMPANY.name == "Meridian Components"
    assert "electronics" in COMPANY.industry and COMPANY.hq and COMPANY.description


def test_roster_is_deterministic_unique_and_never_names_the_company() -> None:
    a, b = _roster(42), _roster(42)
    assert a == b
    assert len({n for _, n in a}) == len(a)
    assert _roster(43) != a
    assert not any(COMPANY.name.split()[0] in n for _, n in _roster(7, 400))


def test_every_name_maps_back_to_a_kind_of_its_category_and_gets_its_lines() -> None:
    rng = random.Random(1)
    for cat, name in _roster(42, 300):
        kind = vendor_kind(name, cat)
        assert KINDS[kind].category == cat
        assert any(d in name for d in KINDS[kind].descriptors)
        assert line_item(rng, cat, name) in KINDS[kind].lines


def test_unknown_names_and_categories_still_get_a_line() -> None:
    rng = random.Random(0)
    assert line_item(rng, "raw_materials", "Some Other Vendor LLC") in KINDS[vendor_kind("Some Other Vendor LLC", "raw_materials")].lines
    assert line_item(rng, None) and line_item(rng, "no_such_category", None)


def test_descriptors_are_unique_across_kinds() -> None:
    seen: dict[str, str] = {}
    for kind, spec in KINDS.items():
        for d in spec.descriptors:
            assert d not in seen, f"{d!r} is in both {seen.get(d)} and {kind}"
            seen[d] = kind
