"""Pure timber-tally logic: parsing, volume formulas, summaries and sampling.

Every volume and money figure is computed with exact ``Fraction`` arithmetic
and only rounded when it is printed. Sampling statistics use floats, because
they need a square root and a t value.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

# pi rounded to 14 decimals. Exact enough for cubic feet and it keeps the
# arithmetic rational, so the tests can compare values without float noise.
PI = Fraction("3.14159265358979")

DEFAULT_GRADES = {1: Fraction(1), 2: Fraction(3, 4), 3: Fraction(1, 2)}
RULES = ("doyle", "cubic")
MAX_DBH = Fraction(300)
MAX_LENGTH = Fraction(100)
SPECIES_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
PLOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
DIRECTIVES = ("rule", "price", "min_dbh", "grades", "plot")

# Two-sided 95% Student t values for 1 to 30 degrees of freedom.
T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}
Z95 = 1.96


@dataclass(frozen=True)
class Problem:
    line: int
    message: str


@dataclass(frozen=True)
class Plot:
    name: str
    acres: Fraction
    line: int


@dataclass(frozen=True)
class Tree:
    line: int
    species: str
    dbh: Fraction
    length: Fraction
    plot: str | None
    grade: int | None


@dataclass
class Cruise:
    rule: str = "doyle"
    price: Fraction = Fraction(0)
    min_dbh: Fraction = Fraction(0)
    grades: dict = field(default_factory=lambda: dict(DEFAULT_GRADES))
    plots: dict = field(default_factory=dict)
    trees: list = field(default_factory=list)


@dataclass(frozen=True)
class TreeVolume:
    tree: Tree
    board_feet: Fraction
    cubic_feet: Fraction
    factor: Fraction
    merchantable: bool
    value: Fraction


@dataclass(frozen=True)
class SpeciesTotal:
    species: str
    trees: int
    merchantable_trees: int
    board_feet: Fraction
    cubic_feet: Fraction
    value: Fraction


@dataclass(frozen=True)
class PlotStat:
    name: str
    acres: Fraction
    trees: int
    board_feet: Fraction

    @property
    def board_feet_per_acre(self) -> Fraction:
        return self.board_feet / self.acres

    @property
    def trees_per_acre(self) -> Fraction:
        return self.trees / self.acres


@dataclass(frozen=True)
class SampleStats:
    n: int
    mean: float
    sd: float
    se: float
    t: float
    half_width: float
    error_pct: float
    low: float
    high: float


class _LineError(ValueError):
    """A problem with one line of the cruise file."""


# ---------------------------------------------------------------- parsing

def _number(token: str, what: str) -> Fraction:
    try:
        return Fraction(token)
    except (ValueError, ZeroDivisionError):
        raise _LineError(f"{what} must be a number, got {token!r}") from None


def _single_number(args: list, word: str) -> Fraction:
    if len(args) != 1:
        raise _LineError(f"{word} takes exactly one number")
    return _number(args[0], word)


def _set_rule(cruise: Cruise, args: list) -> None:
    if len(args) != 1 or args[0].lower() not in RULES:
        raise _LineError("rule must be 'doyle' or 'cubic'")
    cruise.rule = args[0].lower()


def _set_price(cruise: Cruise, args: list) -> None:
    value = _single_number(args, "price")
    if value < 0:
        raise _LineError("price cannot be negative")
    cruise.price = value


def _set_min_dbh(cruise: Cruise, args: list) -> None:
    value = _single_number(args, "min_dbh")
    if value < 0:
        raise _LineError("min_dbh cannot be negative")
    cruise.min_dbh = value


def _set_grades(cruise: Cruise, args: list) -> None:
    if not args:
        raise _LineError("grades needs entries like 1=1.00 2=0.75")
    table = {}
    for token in args:
        key, sep, value = token.partition("=")
        if not sep or not key.isdigit() or not value:
            raise _LineError(f"grade entry {token!r} must look like 1=0.75")
        grade = int(key)
        if grade in table:
            raise _LineError(f"grade {grade} is listed twice")
        factor = _number(value, f"factor for grade {grade}")
        if factor <= 0:
            raise _LineError(f"factor for grade {grade} must be above zero")
        table[grade] = factor
    cruise.grades = table


def _add_plot(cruise: Cruise, args: list, lineno: int) -> None:
    if len(args) != 2:
        raise _LineError("plot must look like: plot NAME ACRES")
    name, acres_text = args
    if not PLOT_RE.match(name):
        raise _LineError(f"invalid plot name {name!r}")
    if name in cruise.plots:
        first = cruise.plots[name].line
        raise _LineError(f"plot {name!r} is already defined on line {first}")
    acres = _number(acres_text, "acres")
    if acres <= 0:
        raise _LineError("acres must be above zero")
    cruise.plots[name] = Plot(name, acres, lineno)


_HANDLERS = {
    "rule": _set_rule,
    "price": _set_price,
    "min_dbh": _set_min_dbh,
    "grades": _set_grades,
}


def _parse_tree(tokens: list, lineno: int) -> Tree:
    if len(tokens) < 3:
        raise _LineError("tree must look like: SPECIES DBH LENGTH [plot=NAME] [grade=N]")
    species = tokens[0]
    if not SPECIES_RE.match(species):
        raise _LineError(f"invalid species code {species!r}")
    dbh = _number(tokens[1], "DBH")
    if not 0 < dbh <= MAX_DBH:
        raise _LineError(f"DBH {tokens[1]} must be above 0 and at most 300 inches")
    length = _number(tokens[2], "length")
    if not 0 < length <= MAX_LENGTH:
        raise _LineError(f"length {tokens[2]} must be above 0 and at most 100 feet")

    options = {}
    for token in tokens[3:]:
        key, sep, value = token.partition("=")
        key = key.lower()
        if not sep or key not in ("plot", "grade") or not value:
            raise _LineError(f"unknown option {token!r}; use plot=NAME or grade=N")
        if key in options:
            raise _LineError(f"option {key}= is given twice")
        options[key] = value

    grade = None
    if "grade" in options:
        if not options["grade"].isdigit():
            raise _LineError("grade must be a whole number")
        grade = int(options["grade"])
    return Tree(lineno, species, dbh, length, options.get("plot"), grade)


def _check_references(cruise: Cruise, problems: list) -> None:
    for tree in cruise.trees:
        if tree.plot is not None and tree.plot not in cruise.plots:
            problems.append(Problem(tree.line, f"unknown plot {tree.plot!r}"))
        if tree.grade is not None and tree.grade not in cruise.grades:
            problems.append(
                Problem(tree.line, f"grade {tree.grade} has no factor in the grades line")
            )
    problems.sort(key=lambda problem: problem.line)


def parse_cruise(text: str) -> tuple:
    """Parse cruise text. Returns ``(Cruise, [Problem, ...])``.

    Every bad line is reported, not just the first one. Trees on a bad line
    are left out of the cruise so the rest of the file can still be checked.
    """
    cruise = Cruise()
    problems = []
    seen = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        body = raw.split("#", 1)[0].strip()
        if not body:
            continue
        tokens = body.split()
        word = tokens[0].lower()
        try:
            if word in DIRECTIVES:
                if word == "plot":
                    _add_plot(cruise, tokens[1:], lineno)
                else:
                    if word in seen:
                        raise _LineError(f"duplicate '{word}' line (first on line {seen[word]})")
                    _HANDLERS[word](cruise, tokens[1:])
                    seen[word] = lineno
            else:
                cruise.trees.append(_parse_tree(tokens, lineno))
        except _LineError as exc:
            problems.append(Problem(lineno, str(exc)))
    _check_references(cruise, problems)
    return cruise, problems


# ---------------------------------------------------------------- volumes

def doyle_board_feet(dbh: Fraction, length: Fraction) -> Fraction:
    """Doyle log rule: ((D - 4) / 4)^2 * L, with D in inches and L in feet."""
    if dbh < 4:
        return Fraction(0)
    return ((dbh - 4) / 4) ** 2 * length


def cubic_feet(dbh: Fraction, length: Fraction) -> Fraction:
    """Volume of a cylinder with the tree's DBH as its diameter."""
    return PI / 4 * (dbh / 12) ** 2 * length


def tree_volume(tree: Tree, cruise: Cruise) -> TreeVolume:
    factor = Fraction(1)
    if tree.grade is not None:
        factor = cruise.grades.get(tree.grade, Fraction(1))
    merchantable = tree.dbh >= cruise.min_dbh
    board = doyle_board_feet(tree.dbh, tree.length)
    cubic = cubic_feet(tree.dbh, tree.length)
    value = Fraction(0)
    if merchantable:
        if cruise.rule == "doyle":
            value = board * factor * cruise.price / 1000
        else:
            value = cubic * factor * cruise.price
    return TreeVolume(tree, board, cubic, factor, merchantable, value)


def all_volumes(cruise: Cruise) -> list:
    return [tree_volume(tree, cruise) for tree in cruise.trees]


def summarize(cruise: Cruise) -> list:
    """Totals per species, sorted by species code. Small trees count as trees only."""
    groups = {}
    for vol in all_volumes(cruise):
        total = groups.setdefault(vol.tree.species, [0, 0, Fraction(0), Fraction(0), Fraction(0)])
        total[0] += 1
        if vol.merchantable:
            total[1] += 1
            total[2] += vol.board_feet
            total[3] += vol.cubic_feet
            total[4] += vol.value
    return [
        SpeciesTotal(species, *totals)
        for species, totals in sorted(groups.items())
    ]


def plot_stats(cruise: Cruise) -> list:
    """Per-plot totals in the order the plots were defined."""
    stats = []
    for plot in cruise.plots.values():
        board = Fraction(0)
        count = 0
        for vol in all_volumes(cruise):
            if vol.tree.plot == plot.name:
                count += 1
                if vol.merchantable:
                    board += vol.board_feet
        stats.append(PlotStat(plot.name, plot.acres, count, board))
    return stats


def unassigned_count(cruise: Cruise) -> int:
    return sum(1 for tree in cruise.trees if tree.plot is None)


def money(amount: Fraction) -> str:
    """Round to the cent (half up) and format as dollars with separators."""
    cents = _cents(amount)
    return f"${cents:,.2f}"


def cents_text(amount: Fraction) -> str:
    """Plain rounded amount with no symbol or separators, for CSV."""
    return f"{_cents(amount):.2f}"


def _cents(amount: Fraction) -> Decimal:
    value = Decimal(amount.numerator) / Decimal(amount.denominator)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- sampling

def t95(df: int) -> float:
    if df < 1:
        raise ValueError("degrees of freedom must be at least 1")
    return T95.get(df, Z95)


def sample_stats(values: list) -> SampleStats | None:
    """Mean, spread and 95% confidence interval of plot values (per acre)."""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in values) / (n - 1))
    se = sd / math.sqrt(n)
    t = t95(n - 1)
    half = t * se
    error = math.inf if mean == 0 else half / mean * 100
    return SampleStats(n, mean, sd, se, t, half, error, mean - half, mean + half)


def plots_needed(values: list, target_pct: float) -> int | None:
    """Smallest plot count whose 95% CI half-width is within target_pct of the mean.

    Uses the standard deviation of the current sample as the estimate. Returns
    None when there are fewer than two plots or the mean is zero.
    """
    stats = sample_stats(values)
    if stats is None or stats.mean <= 0:
        return None
    for n in range(2, 10001):
        error = t95(n - 1) * stats.sd / math.sqrt(n) / stats.mean * 100
        if error <= target_pct:
            return n
    return None


def plot_values(cruise: Cruise) -> list:
    """Board feet per acre for every defined plot, as floats for the statistics."""
    return [float(stat.board_feet_per_acre) for stat in plot_stats(cruise)]
