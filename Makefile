# All logic lives in tasks.py so Windows (no make) and Linux/CI behave identically.
PYTHON ?= python
PACKAGES := core database market_data sentiment decision risk trading pipeline scheduler

.PHONY: install lint format typecheck test cov integration check up down $(addprefix test-,$(PACKAGES))

install lint format typecheck test cov integration check:
	$(PYTHON) tasks.py $@

$(addprefix test-,$(PACKAGES)):
	$(PYTHON) tasks.py $@

up:
	docker compose up -d postgres

down:
	docker compose down
