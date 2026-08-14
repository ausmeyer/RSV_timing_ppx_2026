# RSV prophylaxis timing analysis

Code for **Predictive modeling of Nirsevimab timing to improve infant RSV protection**.

## Reproduce the manuscript results

Install Python 3, R, and standard build tools, then run:

```bash
git clone https://github.com/ausmeyer/RSV_timing_ppx_2026.git
cd RSV_timing_ppx_2026
make setup
make reproduce
```

`make reproduce` downloads the public CDC NSSP and NHSN data through June 20,
2026, runs the complete analysis, creates the figures, and verifies the key
outputs. CDC may revise previously released surveillance values, so small numeric differences from the accepted manuscript are possible.

To rerun without network access after the first successful download:

```bash
make cached
make stats
make verify
```

## Outputs

- `results/figures/`: manuscript Figures 1-5 and Supplemental Figures S1-S2
- `results/tables/`: the 13 tables needed to verify the reported results and figures
- `results/manuscript_stats.txt`: a readable summary of the reported statistics

All data and generated outputs are ignored by Git. The published primary model is
defined directly in `config.yaml`.

## Useful commands

```bash
make test       # run code-level checks
make figures    # rebuild figures from existing tables
make clean      # remove regenerated outputs; keep raw inputs and final upload copies
```

Licensed under the MIT License. Citation metadata are in `CITATION.cff`.
