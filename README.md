# RSV Timing 2025-26 Analysis

This project extends the prior RSV prophylaxis-window analysis with the 2025-26
season. It pulls CDC Socrata data, builds season-level analytic datasets, runs
burden and fixed-window coverage analyses, and writes manuscript tables and
figures.

## Current Working Snapshot

The latest cached raw data were pulled on 2026-05-06:

- `data/raw/nssp_raw_20260506.parquet`
- `data/raw/nhsn_raw_20260506.parquet`

To reproduce the current results from those cached files without hitting the
network:

```sh
make cached
make stats
```

`make cached` regenerates processed data, result tables, and figures. `make stats`
writes `results/manuscript_stats.txt` from the generated tables.

## Fresh Data Run

To pull fresh NSSP and NHSN data from CDC Socrata and rerun the full analysis:

```sh
make all
```

Equivalent direct command:

```sh
python -m src.run_pipeline --force-refresh
```

The default pipeline uses cached raw data only when the cache is at most 1 day
old. For a different cache age:

```sh
python -m src.run_pipeline --max-cache-age-days 30
```

For figures only, using existing processed data and tables:

```sh
make figures
```

## Key Outputs

- `data/processed/nssp_processed.csv`
- `data/processed/nhsn_processed.csv`
- `results/tables/nssp_outside_fraction_by_state.csv`
- `results/tables/nhsn_outside_fraction_by_state.csv`
- `results/tables/nhsn_outside_fraction_all_strata.csv`
- `results/tables/bootstrap_ci_summary.csv`
- `results/tables/longitudinal_consistency.csv`
- `results/tables/nssp_infant_ppx_realistic12mo_state_summary.csv`
- `results/tables/nhsn_infant_ppx_realistic12mo_state_summary.csv`
- `results/tables/nssp_infant_ppx_realistic8mo_state_summary.csv`
- `results/tables/nhsn_infant_ppx_realistic8mo_state_summary.csv`
- `results/tables/infant_ppx_stress_test_window_summary.csv`
- `results/tables/infant_ppx_stress_test_ranking.csv`
- `results/tables/infant_ppx_hospitalizations_averted_early_vs_baseline.csv`
- `results/tables/infant_ppx_hospitalizations_averted_early_vs_baseline_summary.csv`
- `results/tables/infant_ppx_hospitalizations_averted_late_vs_baseline.csv`
- `results/tables/infant_ppx_hospitalizations_averted_extended_vs_baseline.csv`
- `results/tables/infant_ppx_hospitalizations_averted_vs_baseline.csv`
- `results/tables/infant_ppx_realistic_priors.csv`
- `results/figures/fig1_choropleth_grid.pdf`
- `results/figures/fig2_ridgeline_nssp_seasons.pdf`
- `results/figures/fig2_ridgeline_nhsn_seasons_by_agegroup.pdf`
- `results/figures/nssp_fig3_infant_ppx_realistic_delivery_fractional_protection.pdf`
- `results/figures/nhsn_fig3_infant_ppx_realistic_delivery_fractional_protection.pdf`
- `results/figures/nssp_fig4_infant_ppx_realistic_delivery_8mo_censor_fractional_protection.pdf`
- `results/figures/nhsn_fig4_infant_ppx_realistic_delivery_8mo_censor_fractional_protection.pdf`
- `results/figures/combined_infant_ppx_stress_test_window_gains.pdf`
- `results/figures/nssp_infant_ppx_hospitalizations_averted_early_vs_baseline.pdf`
- `results/figures/nssp_infant_ppx_hospitalizations_averted_late_vs_baseline.pdf`
- `results/figures/nssp_infant_ppx_hospitalizations_averted_extended_vs_baseline.pdf`
- `results/manuscript_stats.txt`

## Fixed Window Scenarios

The default analysis now compares four simple fixed calendar windows:

1. Baseline: October 1 to March 31.
2. Early start: September 1 to March 31.
3. Late end: October 1 to April 30.
4. Extended: September 1 to April 30.

The data-driven onset/offset approach is not part of the default output while
we rethink whether it adds enough value over these fixed extensions.

## Infant Protection Model

The main pipeline runs an explainable infant prophylaxis model for the same four
fixed windows. It simulates daily birth cohorts, starting with infants who could
be eligible at the earliest scenario window, then assigns prophylaxis through
newborn/first-week dosing and routine well-child visit opportunities. The main
figure assumptions are realistic-delivery priors: empirical uptake, imperfect
routine-visit timing, first-week dosing, a 6-day pharmacokinetic delay, and a
Moline-grounded smoothed effectiveness curve through 210 days.

The main state-level summary is median person-level fractional protection: for
each infant cohort, the numerator is the amount of that infant's state-season RSV
activity that occurs while protected, and the denominator is all observed RSV
activity during days when that infant is alive and younger than 12 months. A value
of 1.0 means protection covered all of that infant's observed at-risk RSV
exposure.

The 6-day delay is based on the Beyfortus label median time to maximum
nirsevimab concentration. The 8-month eligibility and October-March default
administration period follow CDC/ACIP infant RSV immunization guidance.

The configurable base model can treat protected days as fully covered
(`efficacy_profile: "binary"`) or use a time-varying piecewise-linear
effectiveness curve. The manuscript pipeline overrides the base settings for the
primary infant-model figures and uses the realistic-delivery configuration:
empirical uptake, first-week dosing, imperfect routine-visit timing, 6-day
pharmacokinetic delay, and a Moline et al. JAMA Pediatrics 2026 hospitalization
effectiveness curve through day 210.

The included effectiveness curve uses 93.6% after the day-6 PK delay, 80.7% at
day 45 (the midpoint of the 30-59 day bin), and 78.9% at day 210 (the end of the
observed 130-210 day bin). The published 90-129 day point estimate was lower
than the later 130-210 day estimate, so the model smooths monotonically from the
30-59 day bin to day 210 rather than encoding that non-monotone dip literally.
Figure 3 applies the realistic-delivery priors with the main 12-month first-year
infant RSV exposure denominator. Figure 4 stress-tests the window ranking under
uptake, first-week dosing, visit-delay, and age-censoring scenarios.

The hospitalization translation uses the 100% uptake, otherwise-reference
scenario and compares Early Sep-Mar, Late Oct-Apr, and Extended Sep-Apr with the
Oct-Mar baseline. It converts the state-season NSSP protection gain into
expected RSV hospitalizations averted by
joining 2023 Census state age-under-1 population estimates and a published
untreated infant RSV-associated hospitalization risk of 2,535/215,301 infants
(11.77 per 1,000 infant-seasons) from Pelletier et al. JAMA Network Open 2025.

### Realistic Delivery Priors

The smaller realism set under consideration is uptake, imperfect routine visits,
newborn/first-week dosing, and partial/waning efficacy. These priors are saved
to `results/tables/infant_ppx_realistic_priors.csv` with citations and notes.
They are also listed in `config.yaml` under `infant_ppx_realistic_priors`.
Figures 3 and 4 use these priors by default.

Current citable anchors:

- Nirsevimab uptake: 18.5% infant nirsevimab coverage in the 2023-24 U.S.
  implementation season. This is a lower-bound empirical implementation prior
  because supply constraints affected that season. Source: [MMWR](https://www.cdc.gov/mmwr/volumes/74/wr/mm7431a3.htm).
- Combined infant protection: 57% preliminary 2024-25 infant protection through
  maternal RSV vaccination or nirsevimab. This is useful only if modeling total
  product-derived infant protection, not nirsevimab alone. Source: [CDC ACIP June 2025 presentation](https://www.cdc.gov/acip/downloads/slides-2025-06-25-26/02-Peacock-Mat-Peds-RSV-508.pdf).
- Newborn/first-week dosing: among 2023-24 nirsevimab recipients, 38.1% received
  nirsevimab at age 0-6 days. This is a proxy for birth-hospitalization or
  immediate newborn dosing, not a pure inpatient-only estimate. Source: [MMWR](https://www.cdc.gov/mmwr/volumes/74/wr/mm7431a3.htm).
- Routine visit completion: W30/HEDIS well-child visit completion in the first
  15 months provides a pragmatic anchor for imperfect routine-care opportunities.
  The config currently records 0.59 as the on-schedule/completed-visit prior and
  a 14-day delay as a transparent sensitivity assumption for the delayed pathway.
  Source: [NCQA HEDIS W30](https://www.ncqa.org/hedis/measures/well-child-visits-in-the-first-30-months-of-life/).
- Efficacy: Figures 3 and 4 use a smoothed Moline et al. 2026
  time-since-dose hospitalization effectiveness curve. The raw bins were 93.6%
  for <30 days, 80.7% for 30-59 days, 79.0% for 60-89 days, 56.4% for 90-129
  days, and 78.9% for 130-210 days. Because the 90-129 day estimate is lower
  than the later 130-210 day estimate, the model smooths waning from the 30-59
  day estimate to day 210. Source: [JAMA Pediatrics 2026](https://jamanetwork.com/journals/jamapediatrics/fullarticle/2843213).

### Infant PPX Model Citation Anchors

The generated `results/tables/infant_ppx_model_parameters.csv` includes source
rows for model assumptions. Peer-reviewed or primary sources are preferred where
available:

- Eligibility, seasonal timing, and administration setting: CDC/ACIP infant RSV
  antibody guidance recommends infant RSV antibody for eligible infants younger
  than 8 months who are born during or entering their first RSV season, generally
  October-March in most of the U.S.; eligible infants may receive it during birth
  hospitalization or at any healthcare visit, including well-child visits.
  Source: [CDC RSV immunization guidance for infants and young children](https://www.cdc.gov/rsv/hcp/vaccine-clinical-guidance/infants-young-children.html).
- Pharmacokinetics and duration: the Beyfortus label reports median time to
  maximum concentration of 6 days, terminal half-life of approximately 71 days,
  and protection through 5 months. Primary efficacy endpoints were assessed
  through 150 days. Source: [DailyMed Beyfortus label](https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=2f08fa60-f674-432d-801b-1f9514bd9b39).
- Routine visit opportunities: the AAP Bright Futures/AAP Periodicity Schedule
  supports the first-week newborn visit and the 1-, 2-, 4-, 6-, 9-, and 12-month
  preventive care schedule. Sources: [AAP Periodicity Schedule](https://www.aap.org/periodicityschedule)
  and the peer-reviewed policy statement [2024 Recommendations for Preventive
  Pediatric Health Care](https://doi.org/10.1542/peds.2024-067201).
- Peak postlicensure effectiveness: Moline et al. estimated nirsevimab
  effectiveness of 89% against medically attended RSV-associated ARI and 93%
  against RSV-associated hospitalization during 2023-24. Source: [JAMA Pediatrics](https://jamanetwork.com/journals/jamapediatrics/fullarticle/2827176).
- Time-varying/waning effectiveness: Moline et al. reported nirsevimab
  hospitalization effectiveness by time since receipt through 130-210 days after
  dosing. Figures 3 and 4 use those bins as a smoothed monotone curve rather
  than treating the non-monotone 90-129 day point estimate as a true biological
  rebound. Source: [JAMA Pediatrics](https://jamanetwork.com/journals/jamapediatrics/fullarticle/2843213).
- First-year burden and age censoring: Moline et al. found the largest RSV
  hospitalization reductions among newborns and infants aged 0-11 months, with
  the largest reductions in infants aged 0-2 months. Source: [JAMA Pediatrics](https://jamanetwork.com/journals/jamapediatrics/fullarticle/2843213).
- Uptake sensitivity: the 100% uptake base case is intentionally idealized.
  Empirical uptake scenarios can use CDC RSVVaxView or Boundy et al., which
  estimated 2023-24 infant RSV immunization coverage through nirsevimab or
  maternal vaccination and reported substantial state variation. Source:
  [MMWR](https://www.cdc.gov/mmwr/volumes/74/wr/mm7431a3.htm).
- Infant population denominators: the hospitalization translation uses state
  age-under-1 resident population estimates from the U.S. Census Bureau
  Population Estimates Program, Vintage 2023 single-year age estimates. Source:
  [Census Population Estimates API](https://www.census.gov/data/developers/data-sets/popest-popproj/popest.html).
- Infant RSV hospitalization burden: the hospitalization translation uses the
  observed RSV-associated hospitalization risk among untreated infants in the
  2024-25 Epic Cosmos cohort, 2,535 hospitalizations among 215,301 untreated
  infants. Source: [JAMA Network Open 2025](https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2839288).
- Birth seasonality sensitivity: the base model assumes uniform births, but CDC
  WONDER Natality supports state-month birth counts if we want to replace the
  simplifying assumption with observed natality. Source: [CDC WONDER Natality](https://wonder.cdc.gov/wonder/help/natality.html).

Reference details:

- American Academy of Pediatrics Committee on Practice and Ambulatory Medicine.
  2024 Recommendations for Preventive Pediatric Health Care. Pediatrics.
  2024;154(1):e2024067201. doi:10.1542/peds.2024-067201.
- Moline HL, Toepfer AP, Tannis A, et al. Respiratory Syncytial Virus Disease
  Burden and Nirsevimab Effectiveness in Young Children From 2023-2024. JAMA
  Pediatr. 2025;179(2):179-187. doi:10.1001/jamapediatrics.2024.5572.
- Moline HL, Tannis A, Goldstein L, et al. Effectiveness and Impact of Maternal
  RSV Immunization and Nirsevimab on Medically Attended RSV in US Children.
  JAMA Pediatr. 2026;180(3):314-324.
  doi:10.1001/jamapediatrics.2025.5778.
- Boundy EO, Fast H, Jatlaoui TC, et al. Respiratory Syncytial Virus
  Immunization Coverage Among Infants Through Receipt of Nirsevimab Monoclonal
  Antibody or Maternal Vaccination - United States, October 2023-March 2024.
  MMWR Morb Mortal Wkly Rep. 2025;74(31):484-489.
- Pelletier JH, Rush SZ, Robinette E, et al. Nirsevimab Administration and RSV
  Hospitalization in the 2024-2025 Season. JAMA Netw Open.
  2025;8(9):e2533535. doi:10.1001/jamanetworkopen.2025.33535.

## Notes

- NSSP includes 2023-24, 2024-25, and partial 2025-26 data through the current
  raw-data pull.
- NHSN 2023-24 is excluded by the completeness check for the primary ages 0-4
  outcome in the current cached snapshot.
- All available states and District of Columbia are included. The current NSSP
  cache contains 49 states plus DC (Missouri is not present in the source pull);
  the current NHSN cache contains all 50 states plus DC. Territories, national
  rows, and HHS-region aggregate rows are excluded by `config.yaml`.
- Florida is included when present, but CDC year-round nirsevimab guidance still
  applies, so interpret Florida separately in policy-facing summaries.
- Region-level plots are not written by default. Set
  `output.write_regional_plots: true` in `config.yaml` to generate them.
