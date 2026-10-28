UV ?= uv

.PHONY: test demo bench tracker package

test:
	$(UV) run ruff check .
	$(UV) run pytest

demo:
	@echo "make demo: not built yet (S9, see docs/PLAN.md)"

bench:
	@echo "make bench: not built yet (S8, see docs/PLAN.md)"

tracker:
	$(UV) run python scripts/render_tracker.py docs/TRACKER.md docs/tracker.html

package:
	@echo "make package: not built yet (S15, see docs/PLAN.md)"
