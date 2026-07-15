SHELL := /bin/bash
PREFIX ?= $(HOME)/.local
BINDIR := $(PREFIX)/bin
HERE := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
LINK := $(BINDIR)/crv2pdf

.DEFAULT_GOAL := help
.PHONY: help check install uninstall test

help: ## Show available targets
	@grep -hE '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  make %-10s %s\n", $$1, $$2}'
	@echo "  (override install location with PREFIX=/usr/local)"

check: ## Verify dependencies (fatal only if no renderer backend)
	@ok=1; \
	if command -v php >/dev/null 2>&1 || command -v node >/dev/null 2>&1; then \
		echo "  renderer:         $$(command -v php >/dev/null 2>&1 && echo -n 'php ')$$(command -v node >/dev/null 2>&1 && echo -n 'node')"; \
	else echo "  MISSING renderer: need php (carve-php) or node (carve-js)"; ok=0; fi; \
	command -v python3 >/dev/null 2>&1 && echo "  python3:          yes" || echo "  WARN python3:     missing - needed for HTML/PDF output"; \
	python3 -c 'import websocket' 2>/dev/null && echo "  websocket-client: yes" || echo "  WARN websocket:   missing - 'pip install websocket-client' (PDF only)"; \
	if command -v google-chrome >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1 || [ -n "$$CHROME_BIN" ]; then \
		echo "  chrome:           yes"; \
	else echo "  WARN chrome:      not found - needed for PDF (HTML/MD/TXT work without it)"; fi; \
	[ $$ok -eq 1 ] || { echo "check failed: no renderer backend"; exit 1; }

install: check ## Symlink crv2pdf onto PATH (PREFIX overridable)
	@mkdir -p "$(BINDIR)"
	@ln -sf "$(HERE)/crv2pdf.sh" "$(LINK)"
	@echo "installed: $(LINK) -> $(HERE)/crv2pdf.sh"
	@case ":$$PATH:" in *":$(BINDIR):"*) ;; *) echo "note: $(BINDIR) is not on PATH - add it to use 'crv2pdf' directly";; esac

uninstall: ## Remove the symlink
	@rm -f "$(LINK)" && echo "removed: $(LINK)"

test: ## Run the test harness
	@./tests/test.sh
