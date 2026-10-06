# Analytics reference dataset

What AT-ANA-01…10 run on ([ADR-0029](../../../docs/decisions/ADR-0029-analytics-ranges-and-g4-acceptance.md)): a
dataset, Analytics-valid ranges for it, and the results expected from it, calculated independently of the api.

| File | What it is |
|---|---|
| `dataset.py` → `dataset.json` | Two weeks of what Timebase would return. Front bottom's temperature (°C, SPC) and the nozzle pressure (bar, Dosing_Parameters): twelve production dates, and a dense two hours across the 14:00 shift change with one sample of each excluded kind. Each area's message arrivals give a data gap. Seeded, every time on a 1/8 s grid |
| `ranges.csv` | The Analytics-valid ranges the suite uploads: P03 0–300 °C, P09 0–5 bar, the others wide |
| `independent.py` → `expected.json` | The expected results of 22 queries, from the URS and SDD rules. Python's standard library only: exact fractions for times, 50-digit decimals for values. No api code |
| `expected-pairs-dense-PT1M-AVG.csv` | The paired 1-minute averages of the dense window, for a spreadsheet check |

## Regenerate

```bash
cd tests/fixtures/analytics
python3 dataset.py        # only if the dataset should change
python3 independent.py    # about 10 s
```

The suite checks that `expected.json` is what `independent.py` gives, so a changed dataset without new expected
results fails it.

## Check the statistics in a spreadsheet

Open `expected-pairs-dense-PT1M-AVG.csv` (columns A: time, B: X, C: Y, 110 rows). These must give what
`expected.json` has under `results["dense-PT1M-AVG"].statistics`, and what Centerline shows for that query:

| Spreadsheet | Centerline |
|---|---|
| `=CORREL(B2:B111, C2:C111)` | r (0.8577…) |
| `=SLOPE(C2:C111, B2:B111)`, `=INTERCEPT(C2:C111, B2:B111)` | the equation y = slope·x + intercept |
| `=RSQ(C2:C111, B2:B111)` | R² |
| `=AVERAGE(B2:B111)`, `=STDEV.S(B2:B111)`, `=MIN(…)`, `=MAX(…)` | X's mean, standard deviation, minimum and maximum (and the same for C) |
