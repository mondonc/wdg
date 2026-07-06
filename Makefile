# WDG — build & publish images, run the dev stack, generate documentation.
#
# Images are tagged $(TAG) (git short SHA by default) and latest, under
# $(REGISTRY). Point REGISTRY at your GitLab project registry, e.g.:
#   make push REGISTRY=registry.gitlab.example.org/infra/wdg
# (docker login first; in GitLab CI use $CI_REGISTRY_IMAGE / $CI_JOB_TOKEN.)
# The same "gateway" image runs entry gateways and relays.

REGISTRY ?= registry.example.org/wdg
TAG      ?= $(shell git rev-parse --short HEAD)
IMAGES   := control-plane gateway nginx-pq
COMPOSE  := docker compose -f deploy/docker-compose.yml
# manage.py runs on an internal-plane instance (admin surface).
MANAGE   := $(COMPOSE) exec control-plane-int-1 python manage.py
MANAGE_T := $(COMPOSE) exec -T control-plane-int-1 python manage.py
DOC_DIR  := docs/generated

.PHONY: help build push up seed test e2e doc doc-scenarios logo clean

help: ## List available targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-8s %s\n", $$1, $$2}'

build: ## Build the control-plane, gateway (gw + relays) and nginx-pq images
	docker build -t $(REGISTRY)/control-plane:$(TAG) -t $(REGISTRY)/control-plane:latest server
	docker build -t $(REGISTRY)/gateway:$(TAG)       -t $(REGISTRY)/gateway:latest       gateway
	docker build -t $(REGISTRY)/nginx-pq:$(TAG)      -t $(REGISTRY)/nginx-pq:latest      deploy/nginx-pq

push: build ## Build then push $(TAG) + latest to $(REGISTRY)
	@for image in $(IMAGES); do \
		docker push $(REGISTRY)/$$image:$(TAG) && \
		docker push $(REGISTRY)/$$image:latest || exit 1; \
	done

up: ## Start the dev stack (control plane, mock CAS, nginx-pq)
	$(COMPOSE) up -d --build

seed: ## Seed the demo topology (idempotent)
	$(MANAGE) seed_demo

test: ## Server unit tests + client unit tests
	# Both planes for the test run: the suite exercises client and sync routes.
	$(COMPOSE) exec -e WDG_PLANES=external,internal control-plane-int-1 python manage.py test
	docker run --rm -v $(CURDIR):/repo -w /repo python:3.13-slim \
		python -m unittest wg_client.test_plan wg_client.test_pqtls

e2e: ## Integration suite (CAS login, provisioning, plan, groups)
	$(COMPOSE) run --rm tester

doc: ## Generate the network plan from the database (PDF/SVG diagram + Markdown tables)
	@mkdir -p $(DOC_DIR)
	$(MANAGE_T) topology_export --format dot > $(DOC_DIR)/topology.dot
	$(MANAGE_T) topology_export --format markdown > $(DOC_DIR)/topology.md
	docker build -q -t wdg-doc deploy/doc >/dev/null
	docker run --rm -v $(abspath $(DOC_DIR)):/work -w /work wdg-doc sh -c "\
		dot -Tpdf topology.dot -o topology.pdf && \
		dot -Tsvg topology.dot -o topology.svg && \
		dot -Tpng -Gdpi=110 topology.dot -o topology.png"
	@echo "→ $(DOC_DIR)/topology.{pdf,svg,png,md}"

doc-scenarios: ## Sans-WDG / avec-WDG comparison diagrams (replaces then restores the demo topology; enrolled devices are dropped)
	@mkdir -p $(DOC_DIR)
	# The demo topology is restored by the trap even if a step fails: the
	# database must never be left on a presentation scenario.
	sh -c 'trap "$(MANAGE_T) seed_scenario demo" EXIT; set -e; \
		$(MANAGE_T) seed_scenario sans-wdg; \
		$(MANAGE_T) topology_export --format dot \
			--title "Cas 1 — accès actuels sans WDG : silos DGTW / VPN / bastions" > $(DOC_DIR)/scenario-sans-wdg.dot; \
		$(MANAGE_T) topology_export --format markdown \
			--title "Cas 1 — accès actuels sans WDG" > $(DOC_DIR)/scenario-sans-wdg.md; \
		$(MANAGE_T) seed_scenario avec-wdg; \
		$(MANAGE_T) topology_export --format dot \
			--title "Cas 2 — architecture cible WDG : entrée unifiée, relais admin, failover par centre" > $(DOC_DIR)/scenario-avec-wdg.dot; \
		$(MANAGE_T) topology_export --format markdown \
			--title "Cas 2 — architecture cible WDG" > $(DOC_DIR)/scenario-avec-wdg.md'
	docker build -q -t wdg-doc deploy/doc >/dev/null
	docker run --rm -v $(abspath $(DOC_DIR)):/work -w /work wdg-doc sh -c "\
		for s in sans-wdg avec-wdg; do \
			dot -Tpdf scenario-\$$s.dot -o scenario-\$$s.pdf && \
			dot -Tsvg scenario-\$$s.dot -o scenario-\$$s.svg && \
			dot -Tpng -Gdpi=110 scenario-\$$s.dot -o scenario-\$$s.png; \
		done"
	# Keep the committed reference copies in sync with the generated output.
	for s in sans-wdg avec-wdg; do \
		cp $(DOC_DIR)/scenario-$$s.png $(DOC_DIR)/scenario-$$s.svg \
		   $(DOC_DIR)/scenario-$$s.md docs/scenarios/; \
	done
	@echo "→ $(DOC_DIR)/scenario-{sans,avec}-wdg.{pdf,svg,png,md} (+ docs/scenarios/)"

logo: ## Rebuild logo assets from logo/wdg-logo.tex (needs lualatex + pdftocairo)
	cd logo && lualatex -interaction=nonstopmode wdg-logo.tex >/dev/null
	cd logo && pdftocairo -svg wdg-logo.pdf wdg-logo.svg
	cd logo && pdftocairo -png -r 220 -singlefile wdg-logo.pdf wdg-logo-preview
	cp logo/wdg-logo.svg logo/wdg-mark.svg server/core/static/core/
	rm -f logo/wdg-logo.aux logo/wdg-logo.log logo/wdg-logo.pdf

clean: ## Remove generated documentation
	rm -rf $(DOC_DIR)
