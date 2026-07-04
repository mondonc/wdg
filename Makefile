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
DOC_DIR  := docs/generated

.PHONY: help build push up seed test e2e doc clean

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
	$(COMPOSE) exec control-plane python manage.py seed_demo

test: ## Server unit tests + client unit tests
	$(COMPOSE) exec control-plane python manage.py test
	docker run --rm -v $(CURDIR):/repo -w /repo python:3.13-slim \
		python -m unittest wg_client.test_plan wg_client.test_pqtls

e2e: ## Integration suite (CAS login, provisioning, plan, groups)
	$(COMPOSE) run --rm tester

doc: ## Generate the network plan from the database (PDF/SVG diagram + Markdown tables)
	@mkdir -p $(DOC_DIR)
	$(COMPOSE) exec -T control-plane python manage.py topology_export --format dot > $(DOC_DIR)/topology.dot
	$(COMPOSE) exec -T control-plane python manage.py topology_export --format markdown > $(DOC_DIR)/topology.md
	docker build -q -t wdg-doc deploy/doc >/dev/null
	docker run --rm -v $(abspath $(DOC_DIR)):/work -w /work wdg-doc sh -c "\
		dot -Tpdf topology.dot -o topology.pdf && \
		dot -Tsvg topology.dot -o topology.svg && \
		dot -Tpng -Gdpi=110 topology.dot -o topology.png"
	@echo "→ $(DOC_DIR)/topology.{pdf,svg,png,md}"

clean: ## Remove generated documentation
	rm -rf $(DOC_DIR)
