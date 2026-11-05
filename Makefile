UV ?= uv

.PHONY: v1-up v1-down test test-pg test-keys test-redis test-user demo demo-down demo-clean demo-status \
	demo-env demo-v0 demo-v0-units demo-v0-seed demo-v0-down demo-v0-status gpus bench bench-v0 tracker package hooks \
	decide-up decide-down decide-status

test:
	$(UV) run ruff check .
	$(UV) run pytest

# Key-store tests against a test Postgres (creates and drops perch_test_b_* databases).
PERCH_TEST_KEYS_DATABASE_URL ?= postgresql://postgres:perchtest@127.0.0.1:55432/postgres
test-keys:
	PERCH_TEST_KEYS_DATABASE_URL=$(PERCH_TEST_KEYS_DATABASE_URL) $(UV) run pytest tests/test_crypto.py tests/test_keystore.py tests/test_key_ops.py

# Redis tests: DB 15 of the local test server only (it is flushed).
PERCH_TEST_REDIS_URL ?= redis://127.0.0.1:56379/15
test-redis:
	PERCH_TEST_REDIS_URL=$(PERCH_TEST_REDIS_URL) \
		PERCH_TEST_DATABASE_URL=$${PERCH_TEST_DATABASE_URL:-postgresql://postgres:perchtest@127.0.0.1:55432/postgres} \
		$(UV) run pytest tests/test_redis.py tests/test_auth.py tests/test_oidc.py tests/test_browse_routes.py tests/test_s51_guest_limits.py -p no:cacheprovider

# Postgres tests: needs a superuser URL; the default is the local test server.
# The tests create and drop their own database named perch_test_a_*.
test-pg:
	PERCH_TEST_DATABASE_URL=$${PERCH_TEST_DATABASE_URL:-postgresql://postgres:perchtest@127.0.0.1:55432/postgres} \
		$(UV) run pytest tests/test_store.py tests/test_browse_routes.py tests/test_postgres.py tests/test_jobs_pg.py tests/test_corpus_migrate.py -p no:cacheprovider

# User data (S41 part B): encrypted rows, briefs as user data, delete-my-data, purge, quotas.
# Needs the test Postgres (also used as the keys server) and the test Redis.
test-user:
	PERCH_TEST_DATABASE_URL=$${PERCH_TEST_DATABASE_URL:-postgresql://postgres:perchtest@127.0.0.1:55432/postgres} \
	PERCH_TEST_KEYS_DATABASE_URL=$(PERCH_TEST_KEYS_DATABASE_URL) \
	PERCH_TEST_REDIS_URL=$(PERCH_TEST_REDIS_URL) \
		$(UV) run pytest tests/test_user_data_pg.py tests/test_user_briefs.py tests/test_user_account.py tests/test_key_ops_user.py tests/test_s41_integration.py \
		tests/test_student_account.py tests/test_student_routes.py tests/test_leak_check.py tests/test_saved.py \
		tests/test_scout_v2_account.py tests/test_scout_s45_account.py tests/test_scout_cover_account.py \
		tests/test_s53_profile_account.py tests/test_spend_meter.py tests/test_restore_safety.py tests/test_handoff_job.py tests/test_s48_limits.py -p no:cacheprovider

# The demo: the v1 stack (deploy/compose) as its own Compose project, perch-demo, with the
# CPU worker, so no GPU is needed. One command: `make demo`. `make demo GPU=1` uses the GPU
# worker instead; that needs the NVIDIA container toolkit, and DEMO_WORKER_GPU picks the index.
# Host ports on 127.0.0.1 default away from the fallback (8090) and the v1 deploy (8190, 8200,
# 5433, 6380, 8180). Secrets: .env.demo, made once with dev-only random values (gitignored).
DEMO_PROJECT ?= perch-demo
DEMO_ENV ?= .env.demo
DEMO_WEB_PORT ?= 8300
DEMO_PG_PORT ?= 5434
DEMO_REDIS_PORT ?= 6381
DEMO_KC_PORT ?= 8181
DEMO_WORKER_GPU ?= 3
GPU ?=
DEMO_FILES = -f deploy/compose/docker-compose.v1.yml \
	$(if $(GPU),,-f deploy/compose/docker-compose.cpu.yml) -f deploy/compose/docker-compose.demo.yml
DEMO_COMPOSE = DEMO_WEB_PORT=$(DEMO_WEB_PORT) DEMO_PG_PORT=$(DEMO_PG_PORT) \
	DEMO_REDIS_PORT=$(DEMO_REDIS_PORT) DEMO_KC_PORT=$(DEMO_KC_PORT) \
	PERCH_WORKER_GPU=$(DEMO_WORKER_GPU) DEMO_WORKER_TAG=$(if $(GPU),gpu,cpu) \
	docker compose -p $(DEMO_PROJECT) $(DEMO_FILES) --env-file $(DEMO_ENV)
DEMO_URL = http://127.0.0.1:$(DEMO_WEB_PORT)

demo: demo-env
	@for p in $(DEMO_WEB_PORT) $(DEMO_PG_PORT) $(DEMO_REDIS_PORT) $(DEMO_KC_PORT); do \
	  if (exec 3<>/dev/tcp/127.0.0.1/$$p) 2>/dev/null && \
	     ! $(DEMO_COMPOSE) ps --format '{{.Ports}}' 2>/dev/null | grep -q ":$$p->"; then \
	    echo "Port $$p is used by something else. Set DEMO_WEB_PORT, DEMO_PG_PORT," \
	      "DEMO_REDIS_PORT or DEMO_KC_PORT."; exit 1; fi; done
	$(DEMO_COMPOSE) up -d --build postgres redis keycloak migrate web worker
	$(DEMO_COMPOSE) run --rm --no-deps seed
	@for i in $$(seq 1 180); do curl -sf $(DEMO_URL)/health >/dev/null && break; sleep 2; done; \
	  if ! curl -sf $(DEMO_URL)/health; then echo "The web did not answer /health."; \
	    $(DEMO_COMPOSE) logs --tail 40 web keycloak; exit 1; fi
	@echo
	@echo "Perch demo (v1, Compose project $(DEMO_PROJECT)): $(DEMO_URL)"
	@echo "Loaded: the public Temple awards dataset from data/temple/dataset."
	@echo "The SYNTHETIC sample scholarships are served from data/synthetic."
	@echo "Federal listings (Grants.gov, NIH, NSF) are not loaded: that corpus is copied from the fallback stores"
	@echo "(data/perch.db and data/lance) with perch db migrate-corpus, docs/deploy.md section 5."
	@echo "Guest browsing works. Browser sign-in does not: the OIDC issuer is internal (keycloak:8080)."
	@echo "Stop: make demo-down. Remove its data too: make demo-clean."

# Dev-only secrets for the demo stack, made once. Passwords are hex so they fit in URLs.
demo-env:
	@test -f $(DEMO_ENV) || { umask 077; { \
	  for n in POSTGRES_PASSWORD PERCH_OWNER_PASSWORD PERCH_WEB_PASSWORD PERCH_WORKER_PASSWORD \
	    PERCH_KEYS_PASSWORD KEYCLOAK_ADMIN_PASSWORD PERCH_OIDC_CLIENT_SECRET; do \
	    echo "$$n=$$(openssl rand -hex 24)"; done; \
	  for n in PERCH_MASTER_KEY PERCH_PEPPER PERCH_PEPPER_GUEST PERCH_AUDIT_KEY; do \
	    echo "$$n=$$(openssl rand -base64 32)"; done; \
	  echo "PERCH_MASTER_KEY_ID=demo1"; } > $(DEMO_ENV); echo "Wrote $(DEMO_ENV) (dev-only secrets)."; }

# Only the perch-demo project: containers and network. Volumes are kept.
demo-down:
	$(DEMO_COMPOSE) --profile seed down --remove-orphans

demo-clean:
	$(DEMO_COMPOSE) --profile seed down --remove-orphans --volumes

demo-status:
	@$(DEMO_COMPOSE) ps

# The fallback demo (v0, S9, deploy-2gpu, hybrid): models as systemd user units on two GPUs,
# the app in Docker on 127.0.0.1:8090. One command: `make demo-v0`. GPUs default to 6 and 7.
DEMO_GPU_A ?= 6
DEMO_GPU_B ?= 7
DEMO_UNITS = perch-demo-ollama.service perch-demo-clef-flash.service \
	perch-demo-clef.service perch-demo-models.service
DEMO_CHAT = gemma4:26b-a4b

demo-v0: demo-v0-units demo-v0-seed
	PERCH_UID=$$(id -u) PERCH_GID=$$(id -g) docker compose up -d --build
	@for i in $$(seq 1 60); do curl -sf 127.0.0.1:8090/health >/dev/null && break; sleep 2; done
	@curl -sf 127.0.0.1:8090/health && echo && echo "Perch demo: http://127.0.0.1:8090"

demo-v0-units:
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
demo-v0-seed:
	@test -f data/demo/perch.db || { mkdir -p data/demo && cp data/perch.db data/demo/ && \
	  cp -r data/cache data/lance data/demo/ && echo "seeded data/demo from data/"; }

demo-v0-down:
	docker compose down
	systemctl --user disable --now $(DEMO_UNITS)

demo-v0-status:
	@systemctl --user --no-pager status $(DEMO_UNITS) | grep -E 'Loaded|Active|service -' || true
	@docker compose ps

# GPU memory per service: nvidia-smi processes mapped to their systemd unit or container.
gpus:
	@$(UV) run python scripts/gpus.py

# The v1 back-test (bench/backtest.py --store postgres), as in bench/results/s50_backtest:
# NIH-only, papers before award start, the keyword-only baseline beside the shipped
# dense + Qwen3-Reranker-0.6B path, on pgvector. Needs the `perch_backtest` database
# (11,202 announcements, 5,644 works, Qwen3-Embedding-0.6B vectors; built in S38 with
# `perch db migrate` and `perch db migrate-corpus` from the bench store) and the bench window
# file data/bench/grants_gov_hits.json (gitignored). BENCH_DSN points at the database.
# Per-row CSVs and rerank latencies go to BENCH_OUT. Uses a GPU when one is visible.
BENCH_DSN ?= postgresql://postgres:perchtest@127.0.0.1:55432/perch_backtest
BENCH_PY ?= $(UV) run --extra ml python
BENCH_OUT ?= build/bench/v1_backtest
BENCH_RERANK_CACHE ?= data/bench/cache/rerank_v1.db
bench:
	mkdir -p $(BENCH_OUT) $(dir $(BENCH_RERANK_CACHE)) data/cache
	$(BENCH_PY) -m bench.backtest --store postgres --dsn $(BENCH_DSN) --rerank-in 100 \
		--strata targeted parent --configs keyword-only dense+rerank \
		--reranker Qwen/Qwen3-Reranker-0.6B --rerank-cache $(BENCH_RERANK_CACHE) --out $(BENCH_OUT)

# The fallback's matrix and results table (bench/run.py) on the SQLite and LanceDB bench
# stores (data/bench, python -m bench.corpus); the Clef rows need `make decide-up`.
bench-v0:
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
		  "ui-student.html#/brief/$$($(UV) run python -c 'import json;print(json.load(open("build/replay/student.json"))["brief"]["brief"]["id"])')/routes") \
		$$(test -f build/artifacts/readme.html && echo --readme readme.html)

package:
	$(UV) run python scripts/package.py

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

# The v1 Compose stack (deploy/compose/docker-compose.v1.yml), development ports 8190,
# 5433, 6380 and 8180 on 127.0.0.1. Needs a .env with the v1 entries of .env.example.
V1_COMPOSE = docker compose -f deploy/compose/docker-compose.v1.yml --env-file .env
v1-up:
	$(V1_COMPOSE) up -d --build

v1-down:
	$(V1_COMPOSE) down
