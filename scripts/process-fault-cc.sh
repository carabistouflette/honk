#!/bin/sh
set -eu
for argument do
    if [ "$argument" = -c ]; then
        exec "${HONK_PROCESS_CC:-cc}" "$@"
    fi
done
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "${HONK_PROCESS_CC:-cc}" "$@" "$root/tests/process_fault.c" -Wl,--wrap=clock_gettime,--wrap=syscall,--wrap=kill,--wrap=waitpid,--wrap=gp_start,--wrap=gp_wait,--wrap=gp_close,--wrap=honk_process_guard_begin
# Fixture SHA256: 6118aad7be1d1f194b5bcda621fc6f601067769109bba929bcae2027967f459a
