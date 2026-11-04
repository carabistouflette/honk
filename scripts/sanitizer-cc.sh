#!/bin/sh
# Clang rejects the link-only -no-pie flag on -c under Honk's -Werror policy.
for argument do
    if [ "$argument" = -c ]; then
        exec "${HONK_SANITIZER_CC:-gcc}" -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie "$@"
    fi
done
exec "${HONK_SANITIZER_CC:-gcc}" -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie "$@"
