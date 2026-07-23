.DEFAULT_GOAL := help

.PHONY: help lint format test shellcheck yamllint gitleaks pre-commit setup

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup:  ## Install pre-commit hooks
	uvx pre-commit install

shellcheck:  ## Lint all shell scripts with shellcheck
	shellcheck $(shell git ls-files '**/*.sh')

yamllint:  ## Lint YAML files (compose configs)
	@uvx --from yamllint yamllint -d relaxed docker-compose.*.yml

gitleaks:  ## Scan for secrets in git history
	@uvx --from gitleaks gitleaks detect --log-opts "HEAD~..HEAD"

pre-commit:  ## Run all pre-commit hooks
	uvx --from pre-commit pre-commit run --all-files

lint: shellcheck yamllint gitleaks  ## Run all linters

test:  ## Run pre-commit as the test suite (CI parity)
	uvx --from pre-commit pre-commit run --all-files

format:  ## Auto-format shell scripts (shfmt)
	shfmt -i 2 -ci -s -w $(shell git ls-files '**/*.sh')

clean:  ## Remove pre-commit cache
	rm -rf .pre-commit-cache
