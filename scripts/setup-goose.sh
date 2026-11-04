#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
revision=$(cat GOOSE_REVISION)
if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'GOOSE_REVISION must be a full lowercase commit hash\n' >&2
    exit 1
fi
upstream=https://github.com/aardappel/goose.git
toolchain_dir="$PWD/.toolchain/goose"
# Bootstrap runs before Honk exists, so enforce the CLI's Git policy here too.
safe_git() (
    unset GIT_TEMPLATE_DIR GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE \
        GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_NAMESPACE \
        GIT_SHALLOW_FILE GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS GIT_CONFIG \
        GIT_REPLACE_REF_BASE GIT_SSL_NO_VERIFY
    export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
        GIT_TERMINAL_PROMPT=0 GIT_ALLOW_PROTOCOL=https HONK_GIT_SSL_VERIFY=true
    git -c core.hooksPath=/dev/null -c core.fsmonitor=false \
        -c http.sslVerify=true \
        "--config-env=http.$upstream.sslVerify=HONK_GIT_SSL_VERIFY" "$@"
)
if [[ ! -d "$toolchain_dir/.git" ]]; then
    safe_git init "$toolchain_dir"
fi
safe_git -C "$toolchain_dir" fetch --depth 1 -- "$upstream" "$revision"
safe_git -C "$toolchain_dir" checkout --detach "$revision"
if [[ "$(safe_git -C "$toolchain_dir" rev-parse HEAD)" != "$revision" ]]; then
    printf 'Bootstrapped compiler checkout has the wrong revision\n' >&2
    exit 1
fi
cmake -S "$toolchain_dir" -B "$toolchain_dir/build" \
    -DCMAKE_BUILD_TYPE=Release -DGOOSE_BUILTIN_LIBS=none
cmake --build "$toolchain_dir/build" --parallel "${JOBS:-2}"
