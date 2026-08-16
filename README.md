# RSV prophylaxis timing analysis

Code for **Nirsevimab timing and infant RSV infection: Predictive Modeling**.

## Run the manuscript analysis

Requirements: Python 3.10-3.12, R 4.2 or newer, `make`, and internet access to
install dependencies. The manuscript workflow is:

```bash
git clone https://github.com/ausmeyer/RSV_timing_ppx_2026.git
cd RSV_timing_ppx_2026
make setup
make reproduce
```

The release was tested with Python 3.11 and the exact versions in
`requirements.txt`, plus R 4.5.1 with tidyverse 2.0.0, yaml 2.3.12,
lubridate 1.9.4, ggridges 0.5.7, cowplot 1.2.0, sf 1.1-0, and tigris 2.2.1.
Building `sf` from source requires GDAL, GEOS, PROJ, and sqlite3; binary R
packages may already provide these dependencies on supported platforms.

`make reproduce` verifies the SHA-256 manifest for the versioned manuscript input
snapshot in `data/manuscript/`, materializes those exact files into the ignored
runtime cache, creates every table and figure, and runs the manuscript-value and
publication-contract checks. After dependency installation, the analysis itself
does not require network access.

The full longitudinal sensitivity suite typically takes about 30-45 minutes on
a laptop. Detailed progress is written to `pipeline.log`; the console reports
only warnings and the final check result.

To evaluate the same analysis against the current live CDC view through the
configured cutoff, use the explicitly non-manuscript target:

```bash
make live-reproduce
```

CDC may revise surveillance values within the fixed date range, so live results
may differ from the manuscript and are not checked against publication values.
`make cached` reruns offline from whichever files were most recently materialized
or downloaded into `data/raw/`.

## Frozen input provenance

The public `data/manuscript/` directory contains only the immutable inputs needed
to reproduce the manuscript analysis: cutoff-restricted NSSP and NHSN extracts,
the 2023 Census infant-population table, the Census state-geometry source archive,
and the prepared geometry used for Figure 1. `input_manifest.json` records each
file's byte size, SHA-256 digest, source URL or dataset identifier, query scope,
and analysis date range. Runtime downloads, processed data, and generated outputs
remain ignored by Git.

## Outputs

- `results/figures/`: manuscript Figures 1-5 and Supplemental Figures S1-S2
- `results/final_figures/`: publication Figures 1-5 copied from the regenerated
  figure outputs
- `results/tables/`: the 13 tables needed to verify the reported results and figures
- `results/manuscript_stats.txt`: a readable summary of the reported statistics

The primary model is defined in `config.yaml`. In each annual administration
window, uptake is the probability that a previously untreated infant with an
eligible opportunity receives nirsevimab at the first eligible visit. The primary
18.5% value is a modeling calibration informed by reported launch-season
population coverage; its cited source did not directly estimate this conditional
first-opportunity probability. Later visits in the same window do not create
additional modeled opportunities. Infants who remain untreated and younger than
8 months may receive nirsevimab in a later annual window; prior recipients are not
redosed. Year-round administration is evaluated analytically at steady state.

The sensitivity suite contains the primary model plus 10 prespecified variants:
an 8-month exposure censor; 50%, 75%, and 100% uptake; 20% and 60%
newborn/first-week dosing; 0- and 30-day routine-visit delays; rapid waning; and
one window-start opportunity for an otherwise eligible untreated infant with no
remaining routine visit before aging out.

## Useful commands

```bash
make test       # run code-level checks
make frozen-data # verify and materialize the immutable manuscript inputs
make figures    # rebuild figures from existing processed data and tables
make tables     # rebuild tables and statistics without invoking R
make verify     # verify frozen inputs, manuscript values, figures, and assumptions
make verify-live # structurally verify outputs generated from live/local inputs
make live-reproduce # refresh live data and rerun outside the manuscript contract
make clean      # remove regenerated outputs; keep raw inputs and final upload copies
```

Licensed under the MIT License. Citation metadata are in `CITATION.cff`.
