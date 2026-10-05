# All logic lives in tasks.py so Windows (no make) and Linux/CI behave identically.
PYTHON ?= python
PACKAGES := core database market_data selection sentiment decision risk trading pipeline scheduler webapi

.PHONY: install lint format typecheck test cov integration check web up down $(addprefix test-,$(PACKAGES))

install lint format typecheck test cov integration check web:
	$(PYTHON) tasks.py $@

$(addprefix test-,$(PACKAGES)):
	$(PYTHON) tasks.py $@

up:
	docker compose up -d postgres

down:
	docker compose down
