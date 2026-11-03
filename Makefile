GOOSE ?= .toolchain/goose/build/goose
.PHONY: setup format check build test sanitize bench
setup:
	./scripts/setup-goose.sh
format:
	$(GOOSE) format honk.goose src tests
check:
	$(GOOSE) format --check honk.goose src tests
	$(GOOSE) check honk.goose
	git diff --check
build:
	$(GOOSE) build honk.goose -o .build/honk
test:
	$(MAKE) build
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/cli.py
sanitize:
	$(GOOSE) build honk.goose --debug --no-bce --cc $(CURDIR)/scripts/sanitizer-cc.sh -o .build/honk-sanitize
	ASAN_OPTIONS=detect_leaks=0 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/cli.py
bench: build
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/bench.py
