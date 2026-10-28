# Shared helpers for the in-container package test, following vakr's.
# Sourced, not executed. Each check prints PASS or FAIL, and a failure is
# counted rather than aborting, so one run reports every problem.
# shellcheck shell=bash

export DEBIAN_FRONTEND=noninteractive
failures=0

pass() { printf 'PASS  %s\n' "$*"; }
fail() {
    printf 'FAIL  %s\n' "$*"
    failures=$((failures + 1))
}
check() {
    local what=$1
    shift
    if "$@" >/dev/null 2>&1; then pass "$what"; else fail "$what"; fi
}
section() { printf '\n== %s\n' "$*"; }
equals() { [ "$1" = "$2" ]; }
contains() { case $1 in *"$2"*) return 0 ;; *) return 1 ;; esac; }
installed() { [ "$(dpkg-query -W -f='${Status}' "$1" 2>/dev/null)" = "install ok installed" ]; }

apt_get() {
    # apt's own progress output is noise; show it only when apt fails.
    if ! apt-get -o Dpkg::Use-Pty=0 -y "$@" >/tmp/apt.log 2>&1; then
        cat /tmp/apt.log
        return 1
    fi
}

finish() {
    section "summary"
    if [ "$failures" -gt 0 ]; then
        echo "$1: $failures check(s) FAILED"
        exit 1
    fi
    echo "$1: all checks passed"
}
