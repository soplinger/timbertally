"""Tests for the command-line interface. main() is called directly and returns an exit code."""

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from timbertally.cli import main

ROOT = Path(__file__).resolve().parent.parent
NORTH40 = str(ROOT / "examples" / "north40.tally")
BROKEN = str(ROOT / "examples" / "broken.tally")


def test_lint_clean_example_exits_zero(capsys):
    assert main(["lint", NORTH40]) == 0
    assert "OK: 16 trees, 4 plots, rule doyle" in capsys.readouterr().out


def test_lint_broken_file_prints_file_and_line(capsys):
    assert main(["lint", BROKEN]) == 1
    out = capsys.readouterr().out
    assert f"{BROKEN}:2: rule must be" in out
    assert f"{BROKEN}:7: DBH 0 must be above 0" in out
    assert "8 problem(s) found" in out


def test_volume_shows_board_feet_and_value(capsys):
    assert main(["volume", NORTH40]) == 0
    out = capsys.readouterr().out
    assert "392" in out
    assert "$176.40" in out
    assert "small" in out  # the RC 8 tree is below min_dbh


def test_summary_reports_totals_and_small_tree_count(capsys):
    assert main(["summary", NORTH40]) == 0
    out = capsys.readouterr().out
    assert "TOTAL" in out
    assert "Price: $450.00 per 1000 BF" in out
    assert "1 tree(s) below minimum DBH" in out


def test_plots_shows_per_acre_figures(capsys):
    assert main(["plots", NORTH40]) == 0
    out = capsys.readouterr().out
    assert "3280" in out
    assert "1 tree(s) have no plot" in out


def test_sample_reports_plot_count_and_target(capsys):
    assert main(["sample", NORTH40, "--target", "10"]) == 0
    out = capsys.readouterr().out
    assert "Plots: 4" in out
    assert "95% CI" in out
    assert "Target 10%" in out or "Plots needed for 10%" in out


def test_sample_needs_two_plots(tmp_path, capsys):
    single = tmp_path / "one.tally"
    single.write_text("rule doyle\nplot A 1\nDF 18 32 plot=A\n", encoding="utf-8")
    assert main(["sample", str(single)]) == 1
    assert "Need at least two plots" in capsys.readouterr().out


def test_gate_passes_with_a_loose_limit_and_fails_with_a_tight_one(capsys):
    assert main(["gate", NORTH40, "--max-error", "1000"]) == 0
    assert capsys.readouterr().out.startswith("PASS")
    assert main(["gate", NORTH40, "--max-error", "0.0001"]) == 1
    assert capsys.readouterr().out.startswith("FAIL")


def test_gate_fails_on_lint_errors(capsys):
    assert main(["gate", BROKEN, "--max-error", "1000"]) == 1
    assert f"{BROKEN}:2:" in capsys.readouterr().err


def test_export_writes_one_csv_row_per_tree(tmp_path):
    out = tmp_path / "trees.csv"
    assert main(["export", NORTH40, str(out)]) == 0
    with out.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 16
    first = next(r for r in rows if r["dbh_in"] == "18" and r["plot"] == "P1")
    assert first["board_feet"] == "392.00"
    assert first["value_usd"] == "176.40"
    assert first["merchantable"] == "yes"


def test_report_commands_refuse_a_file_with_errors(capsys):
    assert main(["volume", BROKEN]) == 1
    err = capsys.readouterr().err
    assert f"{BROKEN}:5:" in err
    assert "run 'lint' for the full list" in err


def test_missing_file_exits_two(tmp_path, capsys):
    assert main(["lint", str(tmp_path / "nope.tally")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit) as info:
        main(["frobnicate", NORTH40])
    assert info.value.code == 2


def test_module_runs_as_a_program():
    result = subprocess.run(
        [sys.executable, "-m", "timbertally", "summary", "examples/north40.tally"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "TOTAL" in result.stdout
