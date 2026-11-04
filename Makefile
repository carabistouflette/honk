GOOSE ?= .toolchain/goose/build/goose
.PHONY: setup format check build test sanitize bench security portable metadata-test metadata-sanitize
setup:
	./scripts/setup-goose.sh
format:
	python3 scripts/process-fixture.py --update
	$(GOOSE) format honk.goose src tests
check:
	python3 -m py_compile scripts/metadata-test-build.py tests/http_metadata.py
	python3 scripts/process-fixture.py
	python3 scripts/check-vendor.py
	$(GOOSE) format --check honk.goose src tests
	$(GOOSE) check honk.goose
	$(GOOSE) check tests/core.goose
	$(GOOSE) check tests/process.goose
	$(GOOSE) check tests/semver_probe.goose
	$(GOOSE) check tests/process_fault.goose
	git diff --check
build:
	$(GOOSE) build honk.goose -o .build/honk
test:
	$(MAKE) build
	GOOSE=$(abspath $(GOOSE)) python3 tests/native_import.py
	$(GOOSE) run tests/core.goose
	$(GOOSE) build tests/core.goose -o .build/core
	./.build/core
	$(GOOSE) build tests/process.goose -o .build/process-probe
	./.build/process-probe
	./.build/process-probe closed
	./.build/process-probe overflow
	./.build/process-probe signal
	./.build/process-probe missing
	$(GOOSE) build tests/process_fault.goose --cc "$$(python3 scripts/process-fixture.py --path)" -o .build/process-fault
	PROCESS_PROBE=$(CURDIR)/.build/process-probe PROCESS_FAULT=$(CURDIR)/.build/process-fault python3 tests/process_cli.py
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/cli.py
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/text_cli.py
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/logging.py
	$(GOOSE) build tests/semver_probe.goose -o .build/semver-probe
	HONK=$(CURDIR)/.build/honk SEMVER_PROBE=$(CURDIR)/.build/semver-probe GOOSE=$(abspath $(GOOSE)) python3 tests/semver_cli.py
	$(MAKE) metadata-test
sanitize:
	$(GOOSE) build tests/process.goose --debug --no-bce --cc $(CURDIR)/scripts/sanitizer-cc.sh -o .build/process-sanitize
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/process-sanitize closed
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/process-sanitize overflow
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/process-sanitize signal
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/process-sanitize missing
	$(GOOSE) build tests/process_fault.goose --debug --no-bce --cc "$$(python3 scripts/process-fixture.py --path --sanitize)" -o .build/process-fault-sanitize
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 PROCESS_PROBE=$(CURDIR)/.build/process-sanitize PROCESS_FAULT=$(CURDIR)/.build/process-fault-sanitize python3 tests/process_cli.py
	$(GOOSE) build tests/semver_probe.goose --debug --no-bce --cc $(CURDIR)/scripts/sanitizer-cc.sh -o .build/semver-probe-sanitize
	$(GOOSE) build honk.goose --debug --no-bce --cc $(CURDIR)/scripts/sanitizer-cc.sh -o .build/honk-sanitize
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/cli.py
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/text_cli.py
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/logging.py
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize SEMVER_PROBE=$(CURDIR)/.build/semver-probe-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/semver_cli.py
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/security.py
	$(MAKE) metadata-sanitize
portable:
	$(GOOSE) build honk.goose --debug --no-bce --cc $(CURDIR)/scripts/portable-cc.sh -o .build/honk-portable
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-portable GOOSE=$(abspath $(GOOSE)) python3 tests/cli.py CLI.test_binary_source_snapshots_are_independent CLI.test_oversized_staging_file_fails_before_copy CLI.test_package_stages_only_tracked_files
security: build
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/security.py
bench: build
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/bench.py
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) AUDIT_SAMPLES=3 python3 tests/audit_perf.py

metadata-test:
	python3 scripts/metadata-test-build.py --goose "$(abspath $(GOOSE))" --cc gcc --mode release --output .build/honk-http-test
	HONK_METADATA=$(CURDIR)/.build/honk-http-test python3 tests/http_metadata.py
metadata-sanitize:
	python3 scripts/metadata-test-build.py --goose "$(abspath $(GOOSE))" --cc "$(or $(HONK_SANITIZER_CC),gcc)" --mode sanitize --output .build/honk-http-sanitize
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK_METADATA=$(CURDIR)/.build/honk-http-sanitize python3 tests/http_metadata.py
