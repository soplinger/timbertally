# Timbertally

**Offline timber cruise tally: plain-text tree lists in, board feet, cubic feet, stumpage value, per-acre figures and sampling error out.**

Timbertally reads one readable text file describing a forest cruise (trees, sample plots, prices and grade factors) and turns it into Doyle board-foot volumes, cubic-foot volumes, species totals, per-acre expansions, a 95% confidence interval on plot sampling, and a CI gate for sampling quality. It uses only the Python 3 standard library, makes no network calls, and keeps everything in the file you give it.

## Features

- **Plain-text cruise files** with `#` comments, so the data is easy to read, diff and keep under version control.
- **Line-numbered lint** that reports every bad line at once, using `file:line: message`, not just the first error.
- **Doyle log rule** board feet, computed with exact fractions, so fractional DBH such as `18.5` stays exact.
- **Cubic-foot volume** from a cylinder of the tree's DBH and length.
- **Minimum DBH**: smaller trees are still counted but are left out of volume and value.
- **Grade factors**: map grade codes to price multipliers with one `grades` line.
- **Stumpage value** per tree and per species, rounded half-up to the cent only at the end.
- **Species summary** with totals, merchantable tree counts and the price used.
- **Per-plot expansion**: board feet and trees per acre for each sample plot.
- **Sampling statistics**: mean, standard deviation, standard error and a 95% t confidence interval, as a percentage of the mean.
- **Plots needed** for a target sampling error, using the same t-based method.
- **CSV export** of every tree's volumes and value, to a file or to stdout.
- **CI gate** (`gate --max-error`) that exits 1 on lint errors or on sampling error above the limit.
- **Exit codes** for scripts: `0` success, `1` problems or failed gate, `2` unreadable file or bad usage.
- **Deterministic output**: no clock, no randomness, and no locale-dependent sorting.

## Quick start

The repository includes a sample cruise, `examples/north40.tally`: four 0.2-acre plots, 16 trees, a $450 per MBF price and a 10-inch minimum DBH.

```sh
python3 -m timbertally lint examples/north40.tally
```

Expected result:

```
OK: 16 trees, 4 plots, rule doyle
```

Then get the volumes, the species totals and the per-acre figures:

```sh
python3 -m timbertally volume examples/north40.tally
python3 -m timbertally summary examples/north40.tally
python3 -m timbertally plots examples/north40.tally
python3 -m timbertally sample examples/north40.tally --target 10
```

Plot P1 has 656 merchantable board feet on 0.2 acres, which is 3280 board feet per acre. The tree at `DF 18 32` is worth $176.40 at $450 per MBF, because 392 board feet times 1.00 grade factor times $450 per 1000 board feet is $176.40.

To see the line-numbered errors, lint the deliberately broken sample:

```sh
python3 -m timbertally lint examples/broken.tally
```

Output (the path is the one you passed in):

```
examples/broken.tally:2: rule must be 'doyle' or 'cubic'
examples/broken.tally:5: plot 'P1' is already defined on line 4
examples/broken.tally:7: DBH 0 must be above 0 and at most 300 inches
examples/broken.tally:8: DBH must be a number, got 'twelve'
examples/broken.tally:9: unknown plot 'P9'
examples/broken.tally:10: grade 4 has no factor in the grades line
examples/broken.tally:11: unknown option 'colour=red'; use plot=NAME or grade=N
examples/broken.tally:12: option plot= is given twice
8 problem(s) found
```

## Cruise file format

```
rule doyle              # doyle (per 1000 board feet) or cubic (per cubic foot)
price 450               # dollars per unit, for the rule above
min_dbh 10              # trees below this DBH are counted but not valued
grades 1=1.00 2=0.75 3=0.50

plot P1 0.2             # plot NAME ACRES, one line per sample plot

# SPECIES DBH_IN LENGTH_FT [plot=NAME] [grade=N]
DF 18 32 plot=P1 grade=1
WH 12 16 plot=P1
```

Directives `rule`, `price`, `min_dbh` and `grades` may appear only once. Species codes start with a letter. Trees may omit `plot=` and then count toward species totals but not per-acre figures.

## Commands

| Command | What it does |
| --- | --- |
| `lint FILE` | Check the file and list every problem with its line number. |
| `volume FILE` | Print each tree's board feet, cubic feet, grade factor and value. |
| `summary FILE` | Print species totals and the overall value. |
| `plots FILE` | Print board feet and trees per acre for each plot. |
| `sample FILE [--target PCT]` | Print the mean, the 95% CI and the plots needed for a target error. |
| `export FILE OUT.csv` | Write every tree to CSV. Use `-` for stdout. |
| `gate FILE --max-error PCT` | Pass or fail on sampling error. Also fails on lint errors. |

The report commands (`volume`, `summary`, `plots`, `sample`, `export`, `gate`) refuse to run on a file with lint errors and point you to `lint`.

## How to run

Requires Python 3.9 or newer. No install step is needed; run it from the project root:

```sh
python3 -m timbertally COMMAND FILE
```

Use it in CI by adding a gate step. The exit code is 1 when the gate fails:

```sh
python3 -m timbertally gate examples/north40.tally --max-error 15
```

## How to test

The tests use only `pytest`:

```sh
python3 -m pytest -q
```

The suite covers the Doyle and cubic formulas, exact fraction arithmetic, the line-numbered parser, the duplicate and reference checks, rounding, small-tree handling, per-acre expansion, the t-based statistics, plots-needed search, the CLI exit codes and CSV export, plus one end-to-end run of the module as a program.

## Notes on the method

- **Doyle** uses the formula `((D - 4) / 4)^2 * L`, with D the DBH in inches and L the length in feet. Each tree is treated as one log, and its DBH is used as the small-end diameter, so this is an approximation for a whole tree.
- **Cubic feet** use the cylinder formula `pi / 4 * (D / 12)^2 * L`, with pi held to 14 decimals.
- **Confidence intervals** use Student's t for 1 to 30 degrees of freedom and 1.96 beyond that.

## Project layout

```
timbertally/      core.py (parsing, formulas, statistics), cli.py, __main__.py
examples/         north40.tally (sample cruise), broken.tally (error demo)
tests/            test_core.py, test_cli.py
conftest.py       puts the project root on sys.path for pytest
```
