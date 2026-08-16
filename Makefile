PYTHON ?= .venv/bin/python
.DEFAULT_GOAL := help

.PHONY: check-python setup reproduce data analysis cached tables cached-tables figures stats verify test check clean help

check-python:
	python3 -c 'import sys; assert (3, 10) <= sys.version_info[:2] <= (3, 12), "Python 3.10-3.12 is required by requirements.txt"'

setup: check-python
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements.txt
	Rscript scripts/install_r_packages.R

reproduce: data
	$(PYTHON) -m src.run_pipeline --offline
	$(PYTHON) -m src.manuscript_stats
	$(MAKE) check PYTHON=$(PYTHON)

data:
	$(PYTHON) -m src.data_contract --refresh
	Rscript scripts/prepare_state_geometry.R --refresh

analysis: data
	$(PYTHON) -m src.run_pipeline --offline

cached:
	$(PYTHON) -m src.run_pipeline --offline
	$(PYTHON) -m src.manuscript_stats
	$(MAKE) check PYTHON=$(PYTHON)

tables:
	$(PYTHON) -m src.run_pipeline --offline --skip-figures
	$(PYTHON) -m src.manuscript_stats

cached-tables: tables

figures:
	$(PYTHON) -m src.run_pipeline --figures-only

stats:
	$(PYTHON) -m src.manuscript_stats

verify:
	$(PYTHON) scripts/verify_reproduction.py

test:
	$(PYTHON) -m unittest discover -s tests -v

check: test verify

clean:
	rm -rf data/processed results/tables results/figures results/manuscript_stats.txt pipeline.log
	find src scripts tests -type d -name __pycache__ -prune -exec rm -rf {} +

help:
	@echo "make setup      Install Python and R dependencies"
	@echo "make reproduce  Pull cutoff-restricted live data, run the analysis, and check outputs"
	@echo "make cached     Rerun and check outputs offline from the latest local cache"
	@echo "make tables     Rebuild all tables and statistics without R figures"
	@echo "make figures    Rebuild and publish Figures 1-5 plus supplemental figures"
	@echo "make test       Run code-level unit tests"
	@echo "make verify     Run consistency checks on the current pipeline outputs"
	@echo "make clean      Remove generated outputs (raw inputs and final upload copies are preserved)"
