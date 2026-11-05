GOOSE ?= .toolchain/goose/build/goose
.PHONY: setup format check build test sanitize bench security portable metadata-test metadata-sanitize
setup:
	./scripts/setup-goose.sh
format:
	python3 scripts/process-fixture.py --update
	$(GOOSE) format honk.goose src tests bench/utc/driver.goose
check:
	python3 -m py_compile scripts/metadata-test-build.py tests/http_metadata.py tests/build_cache_cli.py bench/dogfood.py bench/utc/run.py bench/utc/test_runner.py
	python3 bench/dogfood.py --self-test
	python3 scripts/process-fixture.py
	python3 scripts/check-vendor.py
	$(GOOSE) format --check honk.goose src tests bench/utc/driver.goose
	$(GOOSE) check honk.goose
	$(GOOSE) check tests/core.goose
	$(GOOSE) check tests/diagnostics_utc.goose
	$(GOOSE) check tests/process.goose
	$(GOOSE) check tests/semver_probe.goose
	$(GOOSE) check tests/process_fault.goose
	$(GOOSE) check tests/tag_select.goose
	$(GOOSE) check tests/tag_catalog.goose
	$(GOOSE) check bench/utc/driver.goose
	git diff --check
build:
	$(GOOSE) build honk.goose -o .build/honk
test:
	$(MAKE) build
	$(MAKE) diagnostics-test
	GOOSE=$(abspath $(GOOSE)) python3 tests/native_import.py
	$(GOOSE) run tests/core.goose
	$(GOOSE) build tests/core.goose -o .build/core
	./.build/core
	$(GOOSE) run tests/tag_select.goose
	$(GOOSE) build tests/tag_select.goose -o .build/tag-select
	./.build/tag-select
	$(GOOSE) run tests/tag_catalog.goose
	$(GOOSE) build tests/tag_catalog.goose -o .build/tag-catalog
	./.build/tag-catalog
	$(GOOSE) build tests/process.goose -o .build/process-probe
	./.build/process-probe
	./.build/process-probe closed
	./.build/process-probe overflow
	./.build/process-probe signal
	./.build/process-probe missing
	$(GOOSE) build tests/process_fault.goose --cc "$$(python3 scripts/process-fixture.py --path)" -o .build/process-fault
	PROCESS_PROBE=$(CURDIR)/.build/process-probe PROCESS_FAULT=$(CURDIR)/.build/process-fault python3 tests/process_cli.py
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/cli.py
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/build_cache_cli.py
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/text_cli.py
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/manifest_edit_cli.py
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/version_deps_cli.py
	HONK=$(CURDIR)/.build/honk GOOSE=$(abspath $(GOOSE)) python3 tests/logging.py
	$(GOOSE) build tests/semver_probe.goose -o .build/semver-probe
	HONK=$(CURDIR)/.build/honk SEMVER_PROBE=$(CURDIR)/.build/semver-probe GOOSE=$(abspath $(GOOSE)) python3 tests/semver_cli.py
	$(MAKE) metadata-test
sanitize:
	$(MAKE) diagnostics-sanitize
	$(GOOSE) build tests/tag_catalog.goose --debug --no-bce --cc $(CURDIR)/scripts/sanitizer-cc.sh -o .build/tag-catalog-sanitize
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/tag-catalog-sanitize
	$(GOOSE) build tests/tag_select.goose --debug --no-bce --cc $(CURDIR)/scripts/sanitizer-cc.sh -o .build/tag-select-sanitize
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/tag-select-sanitize
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
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/build_cache_cli.py
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/text_cli.py
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/logging.py
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize SEMVER_PROBE=$(CURDIR)/.build/semver-probe-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/semver_cli.py
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/security.py
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/manifest_edit_cli.py
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-sanitize GOOSE=$(abspath $(GOOSE)) python3 tests/version_deps_cli.py
	$(MAKE) metadata-sanitize
portable:
	$(GOOSE) build honk.goose --debug --no-bce --cc $(CURDIR)/scripts/portable-cc.sh -o .build/honk-portable
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-portable GOOSE=$(abspath $(GOOSE)) python3 tests/cli.py CLI.test_binary_source_snapshots_are_independent CLI.test_oversized_staging_file_fails_before_copy CLI.test_package_stages_only_tracked_files
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 HONK=$(CURDIR)/.build/honk-portable GOOSE=$(abspath $(GOOSE)) python3 tests/build_cache_cli.py BuildCache.test_verified_hit_republishes_independent_output BuildCache.test_corrupt_missing_and_unsafe_cache_entries
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

.PHONY: diagnostics-test diagnostics-sanitize diagnostics-bench-smoke
diagnostics-bench-smoke:
	mkdir -p .build/utc
	@utc_smoke=$$(mktemp -d .build/utc/ci-XXXXXX); \
	python3 bench/utc/run.py --goose "$(abspath $(GOOSE))" --cc "$(or $(HONK_SANITIZER_CC),gcc)" --smoke --include-file --output "$$utc_smoke" && \
	python3 bench/utc/test_runner.py "$$utc_smoke" && \
	python3 -O bench/utc/test_runner.py "$$utc_smoke"
diagnostics-test:
	mkdir -p .build
	$(GOOSE) run tests/diagnostics_utc.goose
	$(GOOSE) run tests/diagnostics_utc.goose --debug
	$(GOOSE) build tests/diagnostics_utc.goose -o .build/diagnostics-utc
	./.build/diagnostics-utc
	$(GOOSE) build tests/diagnostics_utc.goose --debug --no-bce -o .build/diagnostics-utc-debug
	./.build/diagnostics-utc-debug
diagnostics-sanitize:
	mkdir -p .build
	$(GOOSE) build tests/diagnostics_utc.goose --debug --no-bce --standalone --cc $(CURDIR)/scripts/sanitizer-cc.sh -o .build/diagnostics-utc-sanitize
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/diagnostics-utc-sanitize
	$(GOOSE) build tests/diagnostics_utc.goose -O2 --standalone --cc $(CURDIR)/scripts/sanitizer-cc.sh -o .build/diagnostics-utc-sanitize-release
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 ./.build/diagnostics-utc-sanitize-release
