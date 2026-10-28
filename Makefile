UV ?= uv

.PHONY: test demo bench tracker package hooks

test:
	$(UV) run ruff check .
	$(UV) run pytest

demo:
	@echo "make demo: not built yet (S9, see docs/PLAN.md)"

bench:
	@echo "make bench: not built yet (S8, see docs/PLAN.md)"

# docs/tracker.html for the browser; build/artifacts/tracker.html is the page published as
# the claude.ai tracker artifact (gitignored).
tracker:
	$(UV) run python scripts/render_tracker.py docs/TRACKER.md docs/tracker.html
	$(UV) run python scripts/render_tracker.py docs/TRACKER.md build/artifacts/tracker.html --artifact

package:
	@echo "make package: not built yet (S15, see docs/PLAN.md)"

hooks:
	git config core.hooksPath scripts/git-hooks
