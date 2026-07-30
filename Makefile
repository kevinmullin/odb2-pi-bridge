IMAGE_DEV ?= obd-bridge:dev
IMAGE_SIM ?= obd-elm-sim:latest
SIM_NAME ?= obd-elm-sim
PROFILE ?= generic
SCENARIO ?= normal
SIM_PORT ?= 35000

.PHONY: build lint test ci shell clean simulate simulate-stop simulate-test macos-setup help

help:
	@echo "Targets:"
	@echo "  make build|lint|test|ci  Docker lint suite (bash -n, shellcheck, units)"
	@echo "  make simulate            ELM emu on :$(SIM_PORT) (PROFILE=$(PROFILE) SCENARIO=$(SCENARIO))"
	@echo "  make simulate-test       Smoke-test ATZ/0105 against local simulator"
	@echo "  make simulate-stop       Stop simulator container"
	@echo "  make macos-setup         Host: brew socat + optional launchd (macOS only)"
	@echo "  make shell               Interactive shell in build image"
	@echo "  make clean               Remove project images/containers"
	@echo ""
	@echo "Scenarios: SCENARIO=normal|overheat  Profiles: PROFILE=generic|subaru|nissan"

build lint test ci:
	docker build -t $(IMAGE_DEV) .
	docker run --rm $(IMAGE_DEV)

shell:
	docker build -t $(IMAGE_DEV) .
	docker run --rm -it -v "$(CURDIR):/src" -w /src --entrypoint /bin/bash $(IMAGE_DEV)

simulate:
	docker build -t $(IMAGE_SIM) -f simulator/Dockerfile simulator
	-docker rm -f $(SIM_NAME) >/dev/null 2>&1 || true
	docker run -d --name $(SIM_NAME) -p $(SIM_PORT):35000 \
		-e PROFILE=$(PROFILE) \
		-e SCENARIO=$(SCENARIO) \
		$(IMAGE_SIM)
	@sleep 1
	@echo "Simulator: PROFILE=$(PROFILE) SCENARIO=$(SCENARIO) on 0.0.0.0:$(SIM_PORT)"
	@echo "Car Scanner → Wi-Fi → <this-machine-LAN-IP> port $(SIM_PORT)"
	@echo "Overheat demo: make simulate SCENARIO=overheat  (coolant climbs for ~75s)"
	@echo "Then: make simulate-test"

simulate-stop:
	-docker rm -f $(SIM_NAME) >/dev/null 2>&1 || true
	@echo "Simulator stopped."

simulate-test:
	@python3 simulator/smoke_test.py ATZ
	@python3 simulator/smoke_test.py 0105

macos-setup:
	@test "$$(uname -s)" = "Darwin" || (echo "macos-setup is for macOS only" >&2; exit 1)
	./macos/scripts/setup.sh

clean:
	-docker rm -f $(SIM_NAME) >/dev/null 2>&1 || true
	-docker rmi $(IMAGE_DEV) $(IMAGE_SIM) >/dev/null 2>&1 || true
	@echo "Cleaned."
