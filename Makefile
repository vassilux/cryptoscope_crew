.PHONY: run run-offline test fmt lint

# --- Fichier portefeuille (chemin absolu ou relatif) ---
PORTFOLIO ?= portfolio.json
export PORTFOLIO_FILE = $(PORTFOLIO)

# Python du venv — on évite uv.exe / crewai.exe (trampoline cassé sur Windows)
PYTHON := .venv/Scripts/python.exe

run:
	$(PYTHON) -m cryptoscope_crew.main

run-offline:
	$(PYTHON) -m cryptoscope_crew.main --inputs offline=true

test:
	$(PYTHON) -m pytest tests/ -v --tb=short

fmt:
	$(PYTHON) -m pip install ruff==0.6.9
	$(PYTHON) -m ruff check --select I --fix .
	$(PYTHON) -m ruff format .

lint:
	$(PYTHON) -m ruff check .
