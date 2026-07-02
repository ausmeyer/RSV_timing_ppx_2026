# RSV Timing 2025-26 Analysis

Extends the prior RSV prophylaxis-window analysis through the 2025-26 season.
Pulls CDC NSSP and NHSN data, builds season-level datasets, runs burden and
fixed-window coverage analyses and an infant prophylaxis delivery model, and
writes the manuscript tables and figures.

## Running

```sh
make cached    # reproduce from cached raw data (no network); also builds figures
make all       # pull fresh CDC data and rerun everything
make figures   # regenerate figures only, from existing tables
make stats     # write results/manuscript_stats.txt
```

Latest cached raw pull: 2026-06-29 (`data/raw/*_20260629.parquet`). `make all`
re-fetches only when the cache is older than one day; override with
`python -m src.run_pipeline --max-cache-age-days N` or `--force-refresh`.

Requires Python (`requirements.txt`) and R with `tidyverse`, `yaml`,
`lubridate`, `ggridges`, `cowplot`, `sf`, and `tigris` (choropleths with
Alaska/Hawaii insets; `tigris` downloads Census boundaries once and caches
them). `maps` and `arrow` are optional fallbacks.

## Outputs

Figures (`results/figures/`, PNG + PDF; publication copies in
`results/final_figures/`):

1. `fig1_choropleth_grid` - out-of-window RSV fraction by state and season
2. `fig2_ridgeline_nssp_seasons` - distribution of out-of-window activity
3. `fig3_infant_ppx_september_vs_april_advantage` - September vs April window
   advantage across stress-test scenarios (including the rapid-waning sensitivity)
4. `fig4_infant_ppx_hospitalizations_averted_early_vs_baseline` - per-state
   hospitalizations averted, September start, 100% uptake
5. `fig5_infant_ppx_hospitalizations_averted_primary_vs_full_uptake` - national
   hospitalizations averted, primary model (A) vs 100% uptake (B)

Tables are written to `results/tables/` (out-of-window fractions, bootstrap CIs,
infant-model state summaries, stress-test ranking, and hospitalizations averted);
`make stats` summarizes them into `results/manuscript_stats.txt`.

## Methods summary

Four fixed calendar windows are compared: baseline Oct 1-Mar 31, early Sep 1-Mar
31, late Oct 1-Apr 30, and year-round.

The three seasonal windows are evaluated within each observed season. Year-round
is a continuously running (any-time-of-year) birth-dose program, so it is instead
evaluated at steady state: under uniform daily births and a periodic annual
epidemic the population is stationary, and the activity-weighted protection
reduces to `uptake x mean efficacy over the first-year at-risk window`, which is
independent of the epidemic curve's timing and width. Evaluating year-round within
a single modeled season would otherwise introduce a startup artifact that
spuriously favors early-onset seasons and penalizes late ones.

The infant prophylaxis model simulates daily birth cohorts and assigns nirsevimab
through newborn/first-week dosing and routine well-child visits, using
realistic-delivery priors: empirical uptake, imperfect visit timing, a 6-day
pharmacokinetic delay, and a Moline et al. 2026 time-since-dose hospitalization
effectiveness curve through 210 days (93.6% early, declining to 77% at 130-210
days). The main state-level metric is activity-weighted protection: each
cohort's protected fraction weighted by the cumulative RSV activity (area under
the epidemic curve) it experienced, so cohorts count in proportion to the RSV
they faced. A rapid-waning sensitivity sets the 130-210 day effectiveness to the
lower 95% CI (42%).

The hospitalization translation converts NSSP protection gains into expected RSV
hospitalizations averted using state under-1 population (Census Vintage 2023) and
a published untreated-infant hospitalization risk of 11.77 per 1,000
infant-seasons (Pelletier et al. 2025).

Full parameter values, sources, and citations live in `config.yaml` and are
written with each run to `results/tables/infant_ppx_model_parameters.csv` and
`infant_ppx_realistic_priors.csv`.

## Notes

- NSSP covers 2023-24, 2024-25, and the complete 2025-26 season; the current cache has all
  50 states plus DC.
- NHSN has all 50 states plus DC; 2023-24 is excluded by the completeness check
  for the primary ages 0-4 outcome.
- Territories, national rows, and HHS-region aggregates are excluded by
  `config.yaml`.
- Florida is included where present, but CDC year-round nirsevimab guidance
  applies; interpret it separately in policy-facing summaries.
