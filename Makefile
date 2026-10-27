.DEFAULT_GOAL := help

.PHONY: help lint format test shellcheck yamllint gitleaks caddy-validate pre-commit setup

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup:  ## Install pre-commit hooks
	uvx pre-commit install

shellcheck:  ## Lint all shell scripts with shellcheck
	shellcheck $(shell git ls-files '**/*.sh')

yamllint:  ## Lint YAML files (compose configs)
	@uvx --from yamllint yamllint -d relaxed docker-compose.*.yml

gitleaks:  ## Scan for secrets in git history
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks detect --log-opts "HEAD~..HEAD"; \
	elif command -v docker >/dev/null 2>&1; then \
		docker run --rm -v $$(pwd):/src ghcr.io/gitleaks/gitleaks:v8.30.1 detect --log-opts "HEAD~..HEAD"; \
	else \
		echo "Warning: Neither gitleaks nor docker available; skipping gitleaks scan."; \
	fi

caddy-validate:  ## Validate Caddyfile configuration
	@python3 scripts/validate_caddyfile.py

pre-commit:  ## Run all pre-commit hooks
	uvx --from pre-commit pre-commit run --all-files

lint: shellcheck yamllint gitleaks caddy-validate  ## Run all linters

test:  ## Run pre-commit as the test suite (CI parity)
	uvx --from pre-commit pre-commit run --all-files

format:  ## Auto-format shell scripts (shfmt)
	shfmt -i 2 -ci -s -w $(shell git ls-files '**/*.sh')

clean:  ## Remove pre-commit cache
	rm -rf .pre-commit-cache
