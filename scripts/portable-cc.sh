#!/bin/sh
# Exercise the portable copy implementation under the same native sanitizers.
exec "$(dirname "$0")/sanitizer-cc.sh" -DHONK_PORTABLE_COPY "$@"
