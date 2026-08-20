#!/usr/bin/env bash
# Thin wrapper. Prefer: python3 onboard_tenant.py --all | c
exec python3 "$(cd "$(dirname "$0")" && pwd)/onboard_tenant.py" "$@"
