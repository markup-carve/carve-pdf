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

check: ## Verify dependencies (fatal only if no renderer backend resolves an engine)
	@ok=1; \
	echo "required:"; \
	php_ok=0; node_ok=0; \
	if command -v php >/dev/null 2>&1 && php "$(HERE)/lib/render.php" --probe >/dev/null 2>&1; then php_ok=1; fi; \
	if command -v node >/dev/null 2>&1 && node "$(HERE)/lib/render.mjs" --probe >/dev/null 2>&1; then node_ok=1; fi; \
	if [ $$php_ok -eq 1 ] || [ $$node_ok -eq 1 ]; then \
		echo "  renderer:             $$([ $$php_ok -eq 1 ] && echo -n 'php ')$$([ $$node_ok -eq 1 ] && echo -n 'js')"; \
	else \
		echo "  MISSING renderer:     no Carve engine resolves - nothing can be rendered"; \
		if command -v php >/dev/null 2>&1; then \
			echo "                        php is on PATH but no autoloader provides MarkupCarve\\Carve"; \
			echo "                        composer require markup-carve/carve-php"; \
		fi; \
		if command -v node >/dev/null 2>&1; then \
			echo "                        node is on PATH but @markup-carve/carve was not found"; \
			echo "                        npm install @markup-carve/carve"; \
		fi; \
		[ $$php_ok -eq 1 ] || [ $$node_ok -eq 1 ] || command -v php >/dev/null 2>&1 || command -v node >/dev/null 2>&1 || \
			echo "                        neither php nor node is on PATH"; \
		ok=0; \
	fi; \
	echo "optional:"; \
	command -v python3 >/dev/null 2>&1 && echo "  python3:              yes" || echo "  WARN python3:         missing - no HTML or PDF output (md/txt still work)"; \
	python3 -c 'import pygments' 2>/dev/null && echo "  pygments:             yes" || echo "  WARN pygments:        missing - code fences render unhighlighted (pip install Pygments)"; \
	python3 -c 'import websocket' 2>/dev/null && echo "  websocket-client:     yes" || echo "  WARN websocket-client: missing - no PDF output (pip install websocket-client)"; \
	if [ -n "$$CHROME_BIN" ] || command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1 || command -v chrome >/dev/null 2>&1; then \
		echo "  chrome:               yes"; \
	else echo "  WARN chrome:          missing - no PDF output (HTML/md/txt still work; set \$$CHROME_BIN)"; fi; \
	command -v inotifywait >/dev/null 2>&1 && echo "  inotifywait:          yes" || echo "  WARN inotifywait:     missing - --watch falls back to polling (slower, still works)"; \
	python3 "$(HERE)/lib/assets.py" 2>/dev/null || echo "  WARN client libraries: could not be checked (needs python3)"; \
	[ $$ok -eq 1 ] || { echo "check failed: no renderer backend resolves a Carve engine"; exit 1; }

install: check ## Symlink crv2pdf onto PATH (PREFIX overridable)
	@mkdir -p "$(BINDIR)"
	@ln -sf "$(HERE)/crv2pdf.sh" "$(LINK)"
	@echo "installed: $(LINK) -> $(HERE)/crv2pdf.sh"
	@case ":$$PATH:" in *":$(BINDIR):"*) ;; *) echo "note: $(BINDIR) is not on PATH - add it to use 'crv2pdf' directly";; esac

uninstall: ## Remove the symlink
	@rm -f "$(LINK)" && echo "removed: $(LINK)"

test: ## Run the test harness
	@./tests/test.sh
