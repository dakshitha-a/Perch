UV ?= uv

.PHONY: test demo bench tracker package hooks decide-up decide-down decide-status

test:
	$(UV) run ruff check .
	$(UV) run pytest

demo:
	@echo "make demo: not built yet (S9, see docs/PLAN.md)"

# Back-test matrix and results table (bench/run.py). Needs the bench corpus
# (python -m bench.corpus) and, for the Clef rows, `make decide-up`.
bench:
	$(UV) run --extra ml python -m bench.run

# docs/tracker.html for the browser; build/artifacts/tracker.html is the page published as
# the claude.ai tracker artifact (gitignored), with a UI tab when a replay preview exists
# (scripts/build_ui_preview.py, also gitignored).
tracker:
	$(UV) run python scripts/render_tracker.py docs/TRACKER.md docs/tracker.html
	-$(UV) run python scripts/build_ui_preview.py
	$(UV) run python scripts/render_tracker.py docs/TRACKER.md build/artifacts/tracker.html --artifact \
		$$(test -f build/artifacts/ui.html && echo --ui ui.html)

package:
	@echo "make package: not built yet (S15, see docs/PLAN.md)"

hooks:
	git config core.hooksPath scripts/git-hooks

# Decision-model servers (dev profile): Clef-flash on GPU 1 :8097, Clef on GPU 2 :8098.
# Needs llama.cpp's CUDA build at ~/.local/bin/llama (see docs/HANDOFF.md).
DECIDE_UNITS = perch-clef-flash.service perch-clef.service
decide-up:
	mkdir -p $(HOME)/.config/systemd/user
	cp deploy/systemd/perch-clef-flash.service deploy/systemd/perch-clef.service $(HOME)/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user enable --now $(DECIDE_UNITS)

decide-down:
	systemctl --user disable --now $(DECIDE_UNITS)

decide-status:
	@systemctl --user --no-pager status $(DECIDE_UNITS) | grep -E 'Loaded|Active|service -' || true
	@for p in 8097 8098; do printf "port $$p health: "; curl -s 127.0.0.1:$$p/health || echo down; echo; done
