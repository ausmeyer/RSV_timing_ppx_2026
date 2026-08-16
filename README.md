# RSV prophylaxis timing analysis

Code for **Predictive modeling of nirsevimab timing to improve infant RSV protection**.

## Run the manuscript analysis

Requirements: Python 3.10-3.12, R 4.2 or newer, `make`, and internet access for
the first run. The complete workflow is:

```bash
git clone https://github.com/ausmeyer/RSV_timing_ppx_2026.git
cd RSV_timing_ppx_2026
make setup
make reproduce
```

`make reproduce` runs the analysis procedure using live public CDC NSSP and NHSN
data restricted to the cutoff configured in `config.yaml` (currently June 20,
2026), creates the figures, and runs automated consistency checks. CDC may revise
surveillance values within that date range, so regenerated numeric results may
differ from the submitted manuscript.

The full longitudinal sensitivity suite typically takes about 30-45 minutes on
a laptop. Detailed progress is written to `pipeline.log`; the console reports
only warnings and the final check result.

After one successful download, `make cached` reruns the analysis without network
access using the most recently downloaded local cache:

```bash
make cached
```

## Outputs

- `results/figures/`: manuscript Figures 1-5 and Supplemental Figures S1-S2
- `results/final_figures/`: publication Figures 1-5 copied from the regenerated
  figure outputs
- `results/tables/`: the 13 tables needed to verify the reported results and figures
- `results/manuscript_stats.txt`: a readable summary of the reported statistics

All downloaded data and generated outputs are ignored by Git. The primary model
is defined in `config.yaml`. In each annual administration window, uptake is the
probability that a previously untreated infant with an eligible opportunity
receives nirsevimab at the first eligible visit. Later visits in the same window
do not create additional modeled opportunities. Infants who remain untreated and
younger than 8 months may receive nirsevimab in a later annual window; prior
recipients are not redosed. Year-round administration is evaluated analytically
at steady state.

The sensitivity suite contains the primary model plus 10 prespecified variants:
an 8-month exposure censor; 50%, 75%, and 100% uptake; 20% and 60%
newborn/first-week dosing; 0- and 30-day routine-visit delays; rapid waning; and
one window-start opportunity for an otherwise eligible untreated infant with no
remaining routine visit before aging out.

## Useful commands

```bash
make test       # run code-level checks
make figures    # rebuild figures from existing tables
make tables     # rebuild tables and statistics without invoking R
make verify     # verify the current tables, figures, and primary assumptions
make clean      # remove regenerated outputs; keep raw inputs and final upload copies
```

Licensed under the MIT License. Citation metadata are in `CITATION.cff`.
