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
# manage.py runs on the admin instance (the configuration surface).
MANAGE   := $(COMPOSE) exec control-plane-admin python manage.py
MANAGE_T := $(COMPOSE) exec -T control-plane-admin python manage.py
DOC_DIR  := docs/generated

.PHONY: help build push up seed test e2e e2e-ha doc doc-scenarios build-clients logo clean

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
	# Every plane for the test run: the suite exercises client, sync and admin routes.
	$(COMPOSE) exec -e WDG_PLANES=external,internal,admin control-plane-admin python manage.py test
	docker run --rm -v $(CURDIR):/repo -w /repo python:3.13-slim \
		python -m unittest wg_client.test_plan wg_client.test_pqtls wg_client.test_tunnel

e2e: ## Integration suite (CAS login, provisioning, plan, groups)
	$(COMPOSE) run --rm tester

e2e-ha: ## HA failover checks: agent int-1→int-2, external RR with one instance down (stops/restarts containers)
	bash deploy/tests/ha_failover.sh

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

CLIENT_DIST := dist/clients
# Official WireGuard MSI bundled next to the Windows exe (first-run install).
WIREGUARD_MSI_URL ?= https://download.wireguard.com/windows-client/wireguard-amd64-0.5.3.msi

build-clients: ## All-in-one desktop clients: Linux binaries + Windows .exe + bundled WireGuard MSI (dist/clients/)
	@mkdir -p $(CLIENT_DIST)/linux $(CLIENT_DIST)/windows
	# --- Linux: one-file GUI + CLI binaries, built in Docker ---
	docker run --rm -v $(CURDIR):/repo:ro -v $(abspath $(CLIENT_DIST))/linux:/out python:3.13-slim sh -c "\
		apt-get -qq update >/dev/null && \
		apt-get -qq install -y binutils libgl1 libegl1 libfontconfig1 libglib2.0-0 libdbus-1-3 libxkbcommon0 libgssapi-krb5-2 >/dev/null && \
		cp -r /repo /build && cd /build && rm -rf build dist && \
		pip install -q '.[gui]' pyinstaller && \
		pyinstaller --clean -y --onefile --name wg-client-gui \
			--add-data wg_client/locales:wg_client/locales \
			--add-data wg_client/assets:wg_client/assets \
			--collect-all keyring \
			deploy/clients/gui_entry.py >/dev/null && \
		pyinstaller --clean -y --onefile --name wg-client \
			--add-data wg_client/locales:wg_client/locales \
			--collect-all keyring \
			deploy/clients/cli_entry.py >/dev/null && \
		cp dist/wg-client-gui dist/wg-client /out/ && chown $(shell id -u):$(shell id -g) /out/*"
	# --- Windows: .exe via PyInstaller under Wine (same entry points) ---
	docker run --rm -v $(CURDIR):/repo:ro -v $(abspath $(CLIENT_DIST))/windows:/out \
		batonogov/pyinstaller-windows:latest "\
		mkdir /build && tar -C /repo --exclude=.git --exclude=dist --exclude=docs \
			--exclude=server --exclude=logo -cf - . | tar -C /build -xf - && cd /build && \
		pip install '.[gui]' && \
		pyinstaller --clean -y --onefile --windowed --name wg-client-gui \
			--add-data 'wg_client/locales;wg_client/locales' \
			--add-data 'wg_client/assets;wg_client/assets' \
			--collect-all keyring \
			deploy/clients/gui_entry.py && \
		pyinstaller --clean -y --onefile --name wg-client \
			--add-data 'wg_client/locales;wg_client/locales' \
			--collect-all keyring \
			deploy/clients/cli_entry.py && \
		cp dist/wg-client-gui.exe dist/wg-client.exe /out/"
	# Bundled WireGuard: shipped next to the exe, installed on first run if absent.
	curl -fsSL -o $(CLIENT_DIST)/windows/wireguard-installer.msi $(WIREGUARD_MSI_URL) \
		|| echo "!! MSI WireGuard non téléchargé — déposez-le manuellement : $(WIREGUARD_MSI_URL)"
	@echo "→ $(CLIENT_DIST)/linux/{wg-client-gui,wg-client}  $(CLIENT_DIST)/windows/{wg-client-gui.exe,wg-client.exe,wireguard-installer.msi}"
	@echo "macOS : PyInstaller ne cross-compile pas — lancer les mêmes commandes pyinstaller sur un Mac (voir docs/VALIDATION-CLIENTS.md)."

logo: ## Rebuild logo assets from logo/wdg-logo.tex (needs lualatex + pdftocairo)
	cd logo && lualatex -interaction=nonstopmode wdg-logo.tex >/dev/null
	cd logo && pdftocairo -svg wdg-logo.pdf wdg-logo.svg
	cd logo && pdftocairo -png -r 220 -singlefile wdg-logo.pdf wdg-logo-preview
	cp logo/wdg-logo.svg logo/wdg-mark.svg server/core/static/core/
	rm -f logo/wdg-logo.aux logo/wdg-logo.log logo/wdg-logo.pdf

clean: ## Remove generated documentation
	rm -rf $(DOC_DIR)
