PYTHON ?= .venv/bin/python

.PHONY: setup reproduce data analysis cached figures stats verify test clean help

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements.txt
	Rscript scripts/install_r_packages.R

reproduce:
	$(PYTHON) -m src.data_contract --refresh
	$(PYTHON) -m src.run_pipeline --offline
	$(PYTHON) -m src.manuscript_stats
	$(PYTHON) scripts/verify_reproduction.py

data:
	$(PYTHON) -m src.data_contract --refresh

analysis: data
	$(PYTHON) -m src.run_pipeline --offline

cached:
	$(PYTHON) -m src.run_pipeline --offline

figures:
	$(PYTHON) -m src.run_pipeline --figures-only

stats:
	$(PYTHON) -m src.manuscript_stats

verify:
	$(PYTHON) scripts/verify_reproduction.py

test:
	$(PYTHON) -m unittest discover -s tests -v

clean:
	rm -rf data/processed results/tables results/figures results/manuscript_stats.txt pipeline.log
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

help:
	@echo "make setup      Install Python and R dependencies"
	@echo "make reproduce  Pull fixed-cutoff data, run the analysis, build figures, and verify"
	@echo "make cached     Reproduce offline from the explicit local fixed-cutoff cache"
	@echo "make clean      Remove generated outputs (raw inputs and final upload copies are preserved)"
