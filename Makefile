IMAGE ?= sandbox-runner:latest
PY ?= python3

.PHONY: help install image seccomp test test-integration probe demo demo-hostile cleanup clean

help:
	@echo 'install          pip install the package with dev dependencies'
	@echo 'image            build the immutable sandbox runner image'
	@echo 'seccomp          regenerate sandbox/seccomp.json from the upstream profile'
	@echo 'test             unit tests (no Docker needed)'
	@echo 'test-integration real-Docker tests: probes, isolation, hostile agents'
	@echo 'probe            run the escape-attempt battery inside a sandbox'
	@echo 'demo             benchmark the demo agents (writes results/)'
	@echo 'demo-hostile     run adversarial submissions (fork bomb, memory hog, infinite loop)'
	@echo 'cleanup          force-remove leaked sandbox containers'

install:
	$(PY) -m pip install -e ".[dev]"

image:
	docker build -t $(IMAGE) -f sandbox/Dockerfile sandbox

seccomp:
	$(PY) scripts/generate_seccomp.py

test:
	$(PY) scripts/generate_seccomp.py --check
	$(PY) -m pytest tests/unit

test-integration: image
	SANDBOX_IMAGE=$(IMAGE) $(PY) -m pytest tests/integration -m docker

probe:
	$(PY) -m orchestrator probe --image $(IMAGE)

demo:
	$(PY) -m orchestrator run --image $(IMAGE) --submissions submissions --out results

demo-hostile:
	@echo 'Running adversarial submissions inside locked-down sandboxes only.'
	$(PY) -m orchestrator run --image $(IMAGE) --submissions submissions_hostile --wall-seconds 15 --out results

cleanup:
	$(PY) -m orchestrator cleanup --image $(IMAGE)

clean:
	rm -rf results .pytest_cache build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
