UV ?= uv

.PHONY: test demo demo-units demo-seed demo-down demo-status gpus bench tracker package hooks \
	decide-up decide-down decide-status

test:
	$(UV) run ruff check .
	$(UV) run pytest

# The demo (S9, deploy-2gpu, hybrid): models as systemd user units on two GPUs, the app
# in Docker on 127.0.0.1:8090. One command: `make demo`. GPUs default to 6 and 7.
DEMO_GPU_A ?= 6
DEMO_GPU_B ?= 7
DEMO_UNITS = perch-demo-ollama.service perch-demo-clef-flash.service \
	perch-demo-clef.service perch-demo-models.service
DEMO_CHAT = gemma4:26b-a4b

demo: demo-units demo-seed
	PERCH_UID=$$(id -u) PERCH_GID=$$(id -g) docker compose up -d --build
	@for i in $$(seq 1 60); do curl -sf 127.0.0.1:8090/health >/dev/null && break; sleep 2; done
	@curl -sf 127.0.0.1:8090/health && echo && echo "Perch demo: http://127.0.0.1:8090"

demo-units:
	mkdir -p $(HOME)/.config/systemd/user
	for u in $(DEMO_UNITS); do sed -e "s|@GPU_A@|$(DEMO_GPU_A)|g" -e "s|@GPU_B@|$(DEMO_GPU_B)|g" \
	  -e "s|@REPO@|$(CURDIR)|g" -e "s|@UV@|$$(command -v $(UV))|g" \
	  -e "s|@DOCKER@|$$(command -v docker)|g" deploy/systemd/demo/$$u \
	  > $(HOME)/.config/systemd/user/$$u; done
	systemctl --user daemon-reload
	systemctl --user enable --now $(DEMO_UNITS)
	@for p in 11437/api/tags 8095/health 8094/health 8093/health; do \
	  for i in $$(seq 1 90); do curl -sf 127.0.0.1:$$p >/dev/null && break; sleep 2; done; \
	  printf "127.0.0.1:$$p "; curl -sf -o /dev/null -w "%{http_code}\n" 127.0.0.1:$$p || echo down; done
	curl -sf 127.0.0.1:11437/api/generate -d '{"model": "$(DEMO_CHAT)", "keep_alive": -1}' >/dev/null

# A separate demo store, seeded once from the dev store (briefs, caches, the index).
demo-seed:
	@test -f data/demo/perch.db || { mkdir -p data/demo && cp data/perch.db data/demo/ && \
	  cp -r data/cache data/lance data/demo/ && echo "seeded data/demo from data/"; }

demo-down:
	docker compose down
	systemctl --user disable --now $(DEMO_UNITS)

demo-status:
	@systemctl --user --no-pager status $(DEMO_UNITS) | grep -E 'Loaded|Active|service -' || true
	@docker compose ps

# GPU memory per service: nvidia-smi processes mapped to their systemd unit or container.
gpus:
	@$(UV) run python scripts/gpus.py

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
	-test -f build/replay/student.json && $(UV) run python scripts/build_ui_preview.py \
		build/replay/student.json --out build/artifacts/ui-student.html
	-$(UV) run --with markdown python scripts/build_readme_preview.py
	$(UV) run python scripts/render_tracker.py docs/TRACKER.md build/artifacts/tracker.html --artifact \
		$$(test -f build/artifacts/ui.html && echo --ui ui.html) \
		$$(test -f build/artifacts/ui-student.html && echo --ui-student \
		  "ui-student.html#/brief/$$(python3 -c 'import json;print(json.load(open("build/replay/student.json"))["brief"]["brief"]["id"])')/routes") \
		$$(test -f build/artifacts/readme.html && echo --readme readme.html)

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
