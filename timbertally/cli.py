"""Command-line interface for timbertally.

Exit codes: 0 success, 1 problems found or gate failed, 2 file or usage error.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .core import (
    all_volumes,
    cents_text,
    money,
    parse_cruise,
    plot_stats,
    plot_values,
    plots_needed,
    sample_stats,
    summarize,
    unassigned_count,
)

HELP = {
    "lint": "check the cruise file and report line-numbered errors",
    "volume": "per-tree Doyle board feet, cubic feet and value",
    "summary": "totals by species with stumpage value",
    "plots": "per-plot board feet and trees per acre",
    "sample": "sampling error, 95% confidence interval and plots needed",
    "export": "write per-tree volumes to CSV",
    "gate": "CI gate: fail on lint errors or sampling error above a limit",
}


def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("must be above zero")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="timbertally",
        description="Offline timber cruise tally: plain-text tree lists in, volumes and values out.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for name, text in HELP.items():
        cmd = sub.add_parser(name, help=text, description=text)
        cmd.add_argument("file", help="cruise file (plain text)")
        if name == "sample":
            cmd.add_argument(
                "--target", type=_positive_float, default=10.0,
                help="target sampling error in percent (default: 10)",
            )
        if name == "export":
            cmd.add_argument("out", help="CSV output path, or - for stdout")
        if name == "gate":
            cmd.add_argument(
                "--max-error", type=_positive_float, required=True,
                help="largest allowed sampling error in percent",
            )
    return parser


def _print_problems(file: str, problems: list, stream) -> None:
    for problem in problems:
        print(f"{file}:{problem.line}: {problem.message}", file=stream)


def _table(headers: list, rows: list) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    lines = ["  ".join(h.ljust(widths[i]) if i == 0 else h.rjust(widths[i])
                       for i, h in enumerate(headers))]
    for row in rows:
        lines.append("  ".join(c.ljust(widths[i]) if i == 0 else c.rjust(widths[i])
                               for i, c in enumerate(row)))
    return "\n".join(lines)


def _bf(value) -> str:
    return str(int(round(value)))


def _cmd_lint(file: str, cruise, problems: list) -> int:
    if problems:
        _print_problems(file, problems, sys.stdout)
        print(f"{len(problems)} problem(s) found")
        return 1
    print(f"OK: {len(cruise.trees)} trees, {len(cruise.plots)} plots, rule {cruise.rule}")
    return 0


def _cmd_volume(cruise) -> int:
    rows = []
    for vol in all_volumes(cruise):
        tree = vol.tree
        rows.append([
            str(tree.line), tree.species, f"{float(tree.dbh):g}", f"{float(tree.length):g}",
            tree.plot or "-", str(tree.grade) if tree.grade is not None else "-",
            _bf(vol.board_feet), f"{float(vol.cubic_feet):.1f}", money(vol.value),
            "merch" if vol.merchantable else "small",
        ])
    print(_table(["LINE", "SPECIES", "DBH", "LEN", "PLOT", "GRADE", "BF", "FT3", "VALUE", "STATUS"], rows))
    return 0


def _cmd_summary(cruise) -> int:
    totals = summarize(cruise)
    rows = [
        [t.species, str(t.trees), str(t.merchantable_trees), _bf(t.board_feet),
         f"{float(t.cubic_feet):.1f}", money(t.value)]
        for t in totals
    ]
    all_trees = sum(t.trees for t in totals)
    merch = sum(t.merchantable_trees for t in totals)
    board = sum(t.board_feet for t in totals)
    cubic = sum(t.cubic_feet for t in totals)
    value = sum(t.value for t in totals)
    rows.append(["TOTAL", str(all_trees), str(merch), _bf(board), f"{float(cubic):.1f}", money(value)])
    print(_table(["SPECIES", "TREES", "MERCH", "BF", "FT3", "VALUE"], rows))
    unit = "per 1000 BF" if cruise.rule == "doyle" else "per cubic foot"
    print(f"Price: {money(cruise.price)} {unit}; minimum DBH {float(cruise.min_dbh):g} in")
    small = all_trees - merch
    if small:
        print(f"{small} tree(s) below minimum DBH left out of volume and value")
    return 0


def _cmd_plots(cruise) -> int:
    stats = plot_stats(cruise)
    if not stats:
        print("No plots defined in this cruise.")
        return 0
    rows = [
        [s.name, f"{float(s.acres):g}", str(s.trees), _bf(s.board_feet),
         _bf(s.board_feet_per_acre), f"{float(s.trees_per_acre):.1f}"]
        for s in stats
    ]
    print(_table(["PLOT", "ACRES", "TREES", "BF", "BF/AC", "TREES/AC"], rows))
    unassigned = unassigned_count(cruise)
    if unassigned:
        print(f"{unassigned} tree(s) have no plot and are not counted per acre")
    return 0


def _cmd_sample(cruise, target: float) -> int:
    values = plot_values(cruise)
    stats = sample_stats(values)
    if stats is None:
        print("Need at least two plots to estimate sampling error.")
        return 1
    print(f"Plots: {stats.n}")
    print(f"Mean: {stats.mean:.1f} BF/ac   SD: {stats.sd:.1f}   SE: {stats.se:.1f}")
    print(f"95% CI: {stats.low:.1f} to {stats.high:.1f} BF/ac (t = {stats.t:.3f})")
    print(f"Sampling error: {stats.error_pct:.1f}% of the mean")
    needed = plots_needed(values, target)
    if needed is None:
        print(f"Plots needed for {target:g}%: cannot be estimated (mean is zero)")
    elif needed <= stats.n:
        print(f"Target {target:g}% met: {stats.n} plots is enough (need {needed})")
    else:
        print(f"Target {target:g}%: need {needed} plots, {needed - stats.n} more than now")
    return 0


def _cmd_export(cruise, out: str) -> int:
    fields = ["line", "species", "dbh_in", "length_ft", "plot", "grade",
              "board_feet", "cubic_feet", "merchantable", "value_usd"]
    handle = sys.stdout if out == "-" else open(out, "w", newline="", encoding="utf-8")
    try:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for vol in all_volumes(cruise):
            tree = vol.tree
            writer.writerow([
                tree.line, tree.species, f"{float(tree.dbh):g}", f"{float(tree.length):g}",
                tree.plot or "", tree.grade if tree.grade is not None else "",
                f"{float(vol.board_feet):.2f}", f"{float(vol.cubic_feet):.2f}",
                "yes" if vol.merchantable else "no", cents_text(vol.value),
            ])
    finally:
        if handle is not sys.stdout:
            handle.close()
    if out != "-":
        print(f"Wrote {len(cruise.trees)} rows to {out}")
    return 0


def _cmd_gate(file: str, cruise, max_error: float) -> int:
    stats = sample_stats(plot_values(cruise))
    if stats is None:
        print(f"FAIL: {file} needs at least two plots to check sampling error")
        return 1
    passed = stats.error_pct <= max_error
    verdict = "PASS" if passed else "FAIL"
    print(f"{verdict}: sampling error {stats.error_pct:.1f}% "
          f"(limit {max_error:g}%) over {stats.n} plots")
    return 0 if passed else 1


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        text = Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"timbertally: cannot read {args.file}: {exc.strerror}", file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print(f"timbertally: {args.file} is not UTF-8 text", file=sys.stderr)
        return 2

    cruise, problems = parse_cruise(text)
    if args.command == "lint":
        return _cmd_lint(args.file, cruise, problems)
    if problems:
        _print_problems(args.file, problems, sys.stderr)
        print(f"timbertally: {len(problems)} problem(s); run 'lint' for the full list",
              file=sys.stderr)
        return 1

    if args.command == "volume":
        return _cmd_volume(cruise)
    if args.command == "summary":
        return _cmd_summary(cruise)
    if args.command == "plots":
        return _cmd_plots(cruise)
    if args.command == "sample":
        return _cmd_sample(cruise, args.target)
    if args.command == "export":
        return _cmd_export(cruise, args.out)
    return _cmd_gate(args.file, cruise, args.max_error)
