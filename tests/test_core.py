"""Tests for the pure logic in timbertally.core."""

from fractions import Fraction
from pathlib import Path

import pytest

from timbertally.core import (
    cubic_feet,
    doyle_board_feet,
    money,
    parse_cruise,
    plot_stats,
    plots_needed,
    sample_stats,
    summarize,
    t95,
    tree_volume,
    unassigned_count,
)

ROOT = Path(__file__).resolve().parent.parent
NORTH40 = ROOT / "examples" / "north40.tally"

BROKEN = """\
# Deliberately broken cruise, used to show line-numbered errors.
rule timber
price 450
plot P1 0.2
plot P1 0.5
DF 18 32 plot=P1 grade=1
DF 0 32
WH twelve 16
XX-9 14 16 plot=P9
DF 16 32 grade=4
DF 15 32 colour=red
DF 15 32 plot=P1 plot=P1
"""


def test_doyle_board_feet_follows_the_formula():
    # ((18 - 4) / 4) ** 2 * 32 = 3.5 ** 2 * 32 = 392
    assert doyle_board_feet(Fraction(18), Fraction(32)) == 392
    assert doyle_board_feet(Fraction(14), Fraction(32)) == 200


def test_doyle_board_feet_is_zero_below_four_inches():
    assert doyle_board_feet(Fraction(3), Fraction(16)) == 0
    assert doyle_board_feet(Fraction(4), Fraction(16)) == 0


def test_fractional_dbh_is_exact():
    # ((18.5 - 4) / 4) ** 2 * 32 = 3.625 ** 2 * 32 = 420.5 exactly
    assert doyle_board_feet(Fraction("18.5"), Fraction(32)) == Fraction("420.5")


def test_cubic_feet_is_a_cylinder():
    # pi / 4 * (12 / 12) ** 2 * 16 = 4 * pi
    assert float(cubic_feet(Fraction(12), Fraction(16))) == pytest.approx(12.566370614, rel=1e-9)


def test_example_file_parses_cleanly():
    cruise, problems = parse_cruise(NORTH40.read_text(encoding="utf-8"))
    assert problems == []
    assert len(cruise.trees) == 16
    assert list(cruise.plots) == ["P1", "P2", "P3", "P4"]
    assert unassigned_count(cruise) == 1


def test_every_bad_line_is_reported_with_its_line_number():
    _, problems = parse_cruise(BROKEN)
    assert [p.line for p in problems] == [2, 5, 7, 8, 9, 10, 11, 12]
    assert "rule must be" in problems[0].message
    assert "plot 'P1' is already defined on line 4" in problems[1].message
    assert "unknown plot 'P9'" in problems[4].message
    assert "grade 4 has no factor" in problems[5].message


def test_duplicate_directive_points_at_the_first_line():
    _, problems = parse_cruise("price 1\nprice 2\n")
    assert [(p.line, "first on line 1" in p.message) for p in problems] == [(2, True)]


def test_unknown_and_repeated_tree_options_are_errors():
    _, problems = parse_cruise("DF 10 16 colour=red\nDF 10 16 grade=1 grade=2\n")
    assert [p.line for p in problems] == [1, 2]
    assert "unknown option 'colour=red'" in problems[0].message
    assert "given twice" in problems[1].message


def test_money_rounds_half_up_to_the_cent():
    assert money(Fraction(1, 200)) == "$0.01"  # 0.005 rounds up
    assert money(Fraction(4, 1000)) == "$0.00"
    assert money(Fraction(1234567, 100)) == "$12,345.67"


def test_tree_value_is_exact_before_rounding():
    cruise, problems = parse_cruise("rule doyle\nprice 450\nDF 18 32 grade=1\n")
    assert problems == []
    vol = tree_volume(cruise.trees[0], cruise)
    # 392 BF * 1.00 grade factor * $450 per MBF
    assert vol.value == Fraction(176400, 1000)
    assert money(vol.value) == "$176.40"


def test_small_trees_are_counted_but_not_valued():
    cruise, problems = parse_cruise("min_dbh 10\nprice 450\nRC 8 16\n")
    assert problems == []
    vol = tree_volume(cruise.trees[0], cruise)
    assert vol.merchantable is False
    assert vol.value == 0
    (total,) = summarize(cruise)
    assert (total.trees, total.merchantable_trees) == (1, 0)
    assert total.board_feet == 0


def test_summary_groups_by_species_in_sorted_order():
    cruise, _ = parse_cruise(NORTH40.read_text(encoding="utf-8"))
    totals = {t.species: t for t in summarize(cruise)}
    assert list(totals) == ["DF", "RC", "WH"]
    assert (totals["DF"].trees, totals["RC"].trees, totals["WH"].trees) == (9, 3, 4)


def test_plot_board_feet_per_acre_excludes_small_trees():
    cruise, _ = parse_cruise(NORTH40.read_text(encoding="utf-8"))
    p1 = plot_stats(cruise)[0]
    assert p1.name == "P1"
    assert p1.trees == 4
    # DF 18/32 (392) + DF 14/32 (200) + WH 12/16 (64); RC 8 is below min_dbh
    assert p1.board_feet == 656
    assert p1.board_feet_per_acre == 3280


def test_sample_stats_matches_hand_calculation():
    stats = sample_stats([10.0, 12.0, 14.0])
    assert stats.n == 3
    assert stats.mean == pytest.approx(12.0)
    assert stats.sd == pytest.approx(2.0)
    # t(2) = 4.303, half width = 4.303 * 2 / sqrt(3), about 41.4% of the mean
    assert stats.error_pct == pytest.approx(41.405, rel=1e-3)


def test_sample_stats_needs_two_plots_and_handles_zero_mean():
    assert sample_stats([5.0]) is None
    assert sample_stats([0.0, 0.0]).error_pct == float("inf")


def test_plots_needed_for_identical_plots_is_two():
    assert plots_needed([5.0, 5.0], 10) == 2


def test_plots_needed_is_the_smallest_count_that_meets_target():
    values = [10.0, 12.0, 14.0, 11.0, 13.0]
    stats = sample_stats(values)

    def error_at(n):
        return t95(n - 1) * stats.sd / n ** 0.5 / stats.mean * 100

    n = plots_needed(values, 5.0)
    assert error_at(n) <= 5.0
    assert n == 2 or error_at(n - 1) > 5.0


def test_t_table_lookup():
    assert t95(1) == 12.706
    assert t95(30) == 2.042
    assert t95(500) == 1.96
    with pytest.raises(ValueError):
        t95(0)


def test_plot_acres_must_be_positive():
    _, problems = parse_cruise("plot A 0\n")
    assert [p.line for p in problems] == [1]
    assert "acres must be above zero" in problems[0].message
