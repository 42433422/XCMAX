# XCMAX monorepo — 一条命令跑起来（P0-3）
# 用法：make setup && make dev
# 工作目录约定：所有 Python/前端路径以 FHD/ 为根。

.PHONY: help setup dev test test-xcagi test-coverage lint openapi-check openapi-check-strict e2e

FHD := FHD
VENV := $(abspath $(FHD)/.venv)
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
REQ_DEV := $(FHD)/requirements-dev.txt
REQ := $(FHD)/requirements.txt
REQUIREMENTS := $(if $(wildcard $(REQ_DEV)),$(REQ_DEV),$(REQ))

help:
	@echo "XCMAX Makefile (macOS/Linux)"
	@echo "  setup          — FHD/.venv + pip install (requirements-dev.txt 或 requirements.txt)"
	@echo "  dev            — 启动 XCAGI (FHD/XCAGI/run.py)"
	@echo "  test           — pytest FHD/tests/"
	@echo "  test-xcagi     — pytest FHD/XCAGI/xcagi_tests (importlib)"
	@echo "  test-coverage  — pytest + app 覆盖率"
	@echo "  lint           — ruff check FHD/app/"
	@echo "  openapi-check  — OpenAPI 一致性脚本"
	@echo "  e2e            — Playwright (FHD/frontend)"

setup:
	@test -d $(VENV) || (cd $(FHD) && python3 -m venv .venv)
	$(PIP) install -r $(REQUIREMENTS)
	@echo "Done. Next: make dev"

dev:
	cd $(FHD)/XCAGI && $(PY) run.py

test:
	cd $(FHD) && $(PY) -m pytest tests/ -q

test-xcagi:
	cd $(FHD) && $(PY) -m pytest XCAGI/xcagi_tests --import-mode=importlib -q

test-coverage:
	cd $(FHD) && $(PY) -m pytest tests/ --cov=app --cov-report=term-missing

lint:
	cd $(FHD) && $(PY) -m ruff check app/

openapi-check:
	cd $(FHD) && PYTHONPATH=. $(PY) scripts/check_openapi_consistency.py

openapi-check-strict:
	cd $(FHD) && PYTHONPATH=. $(PY) scripts/check_openapi_consistency.py --strict

openapi-check-relaxed: openapi-check

e2e:
	bash $(FHD)/scripts/dev/e2e-full.sh

surface-audit-app:
	bash $(FHD)/scripts/dev/run_app_surface_audit.sh

surface-audit-android:
	SURFACE_AUDIT_ANDROID=1 bash $(FHD)/scripts/dev/run_app_surface_audit.sh

android-apk-debug:
	cd $(FHD)/mobile-android && ./gradlew :app:assemblePersonalDebug

android-emulator-setup:
	bash $(FHD)/scripts/dev/setup_android_emulator.sh

android-emulator-start:
	bash $(FHD)/scripts/dev/start_android_emulator.sh

android-emulator-stop:
	bash $(FHD)/scripts/dev/stop_android_emulator.sh
