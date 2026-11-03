#!/bin/sh
exec gcc -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie "$@"
