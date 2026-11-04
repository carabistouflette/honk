GOOSE ?= .toolchain/goose/build/goose
.PHONY: setup format check build test sanitize bench security
setup:
	./scripts/setup-goose.sh
format:
	$(GOOSE) format honk.goose src tests
check:
	$(GOOSE) format --check honk.goose src tests
	$(GOOSE) check honk.goose
	$(GOOSE) check tests/core.goose
	$(GOOSE) check tests/process.goose
	git diff --check
build:
	$(GOOSE) build honk.goose -o .build/honk
test:
	$(MAKE) build
	$(GOOSE) run tests/core.goose
	$(GOOSE) build tests/core.goose -o .build/core
	./.build/core
	$(GOOSE) build tests/process.goose -o .build/process-probe
	./.build/process-probe
	./.build/process-probe closed
	./.build/process-probe overflow
	./.build/process-probe signal
	./.build/process-probe missing
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/cli.py
sanitize:
	$(GOOSE) build tests/process.goose --debug --no-bce --cc $(CURDIR)/scripts/sanitizer-cc.sh -o .build/process-sanitize
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/process-sanitize closed
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/process-sanitize overflow
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/process-sanitize signal
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/process-sanitize missing
	$(GOOSE) build honk.goose --debug --no-bce --cc $(CURDIR)/scripts/sanitizer-cc.sh -o .build/honk-sanitize
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/cli.py
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/security.py
security: build
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/security.py
bench: build
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/bench.py
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) AUDIT_SAMPLES=3 python3 tests/audit_perf.py
