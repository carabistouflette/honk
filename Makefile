GOOSE ?= .toolchain/goose/build/goose
.PHONY: setup format check build test sanitize bench
setup:
	./scripts/setup-goose.sh
format:
	$(GOOSE) format honk.goose src tests
check:
	$(GOOSE) format --check honk.goose src tests
	$(GOOSE) check honk.goose
	$(GOOSE) check tests/core.goose
	git diff --check
build:
	$(GOOSE) build honk.goose -o .build/honk
test:
	$(MAKE) build
	$(GOOSE) run tests/core.goose
	$(GOOSE) build tests/core.goose -o .build/core
	./.build/core
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/cli.py
sanitize:
	$(GOOSE) build honk.goose --debug --no-bce --cc $(CURDIR)/scripts/sanitizer-cc.sh -o .build/honk-sanitize
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/cli.py
bench: build
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/bench.py
