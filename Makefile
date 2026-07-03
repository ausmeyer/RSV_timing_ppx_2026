# RSV Timing 2025-26 Season Extension Pipeline
# Usage: make all

.PHONY: all cached clean data analysis analysis-cached figures stats help

all: analysis
	@echo "Pipeline complete. Results in results/"

cached: analysis-cached
	@echo "Cached-data pipeline complete. Results in results/"

data:
	@echo "Fetching NSSP data from CDC Socrata..."
	python -m src.pull_nssp
	@echo "Fetching NHSN HRD data from CDC Socrata..."
	python -m src.pull_nhsn
	@echo "Data pull complete."

analysis: data
	@echo "Running full analysis pipeline..."
	python -m src.run_pipeline
	@echo "Analysis complete."

analysis-cached:
	@echo "Running full analysis pipeline with latest cached raw data..."
	python -m src.run_pipeline --use-cache
	@echo "Cached analysis complete."

figures:
	@echo "Generating figures..."
	python -c "from src.run_pipeline import generate_figures_only; generate_figures_only()"
	@echo "Figures saved to results/figures/"

stats:
	@echo "Generating manuscript statistics..."
	python -m src.manuscript_stats
	@echo "Statistics saved to results/manuscript_stats.txt"

refresh:
	@echo "Forcing data refresh and re-running pipeline..."
	python -m src.run_pipeline --force-refresh

clean:
	@echo "Cleaning generated files..."
	rm -rf data/raw/*.parquet
	rm -rf data/raw/*.json
	rm -rf data/processed/*.parquet
	rm -rf data/processed/*.csv
	rm -rf results/figures/*
	rm -rf results/tables/*
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete."

help:
	@echo "RSV Timing 2025-26 Season Extension Pipeline"
	@echo ""
	@echo "Usage:"
	@echo "  make all       - Run complete pipeline (data + analysis + figures)"
	@echo "  make cached    - Re-run analysis + figures using latest cached raw data"
	@echo "  make data      - Pull data from CDC Socrata only"
	@echo "  make analysis  - Run analysis (pulls data if needed)"
	@echo "  make analysis-cached - Run analysis using latest cached raw data"
	@echo "  make figures   - Regenerate figures only (requires prior analysis)"
	@echo "  make stats     - Generate manuscript statistics summary"
	@echo "  make refresh   - Force re-fetch data and re-run pipeline"
	@echo "  make clean     - Remove all generated files"
	@echo "  make help      - Show this help message"
	@echo ""
	@echo "Key outputs:"
	@echo "  results/tables/nssp_outside_fraction_by_state.csv"
	@echo "  results/tables/nhsn_outside_fraction_by_state.csv"
	@echo "  results/tables/nhsn_outside_fraction_all_strata.csv   (3 age groups)"
	@echo "  results/tables/bootstrap_ci_summary.csv"
	@echo "  results/tables/longitudinal_consistency.csv"
	@echo "  results/figures/fig1_choropleth_grid.pdf"
	@echo "  results/figures/fig2_ridgeline_nssp_seasons.pdf"
	@echo "  results/figures/fig3_infant_ppx_early_start_advantage_forest.pdf"
	@echo "  results/figures/fig4_infant_ppx_hospitalizations_averted_by_window.pdf"
	@echo "  results/figures/fig5_infant_ppx_hospitalizations_averted_primary_vs_full_uptake.pdf"
	@echo "  results/figures/nssp_fig_supp_timeseries.pdf"
	@echo "  results/figures/nhsn_fig_supp_timeseries.pdf"
	@echo "  results/manuscript_stats.txt"
