.PHONY: check lint types test review validate-dataset eval score compare report

UV := uv run
RUN ?= baseline
K ?= 3
A ?= baseline
B ?=
REPO ?= .
BASE ?= main
HEAD ?= HEAD

check: lint types test

lint:
	$(UV) ruff check .
	$(UV) ruff format --check .

types:
	$(UV) ty check

test:
	$(UV) pytest

review:  ## make review DIFF=path.patch  |  make review REPO=. BASE=main HEAD=my-branch
ifdef DIFF
	$(UV) python -m reviewer.review --diff $(DIFF) --out findings.json
else
	$(UV) python -m reviewer.review --repo $(REPO) --base $(BASE) --head $(HEAD) --out findings.json
endif

validate-dataset:
	$(UV) python -m eval.harness.dataset validate

eval:  ## collect K runs per case into the raw cache, then score (needs ANTHROPIC_API_KEY)
	$(UV) python -m eval.harness.collect --run $(RUN) --k $(K)
	$(UV) python -m eval.harness.score --run $(RUN) --online

score:  ## re-score a run offline from the committed caches; never calls the API
	$(UV) python -m eval.harness.score --run $(RUN)

compare:  ## make compare A=baseline B=exp1
	$(UV) python -m eval.harness.compare --a $(A) --b $(B)


report:  ## make report RUN=exp1 [BASELINE=baseline]
ifdef BASELINE
	$(UV) python -m eval.harness.report --run $(RUN) --baseline $(BASELINE)
else
	$(UV) python -m eval.harness.report --run $(RUN)
endif
