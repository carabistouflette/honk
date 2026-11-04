#!/bin/sh
# Exercise the portable copy implementation under the same native sanitizers.
exec gcc -DHONK_PORTABLE_COPY -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie "$@"
