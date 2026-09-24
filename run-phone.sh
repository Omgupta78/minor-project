#!/usr/bin/env bash
# Start the server so the Android app can reach it.
#
# Same as run.sh, but bound to every network instead of this computer only.
# That one difference is the whole reason this file exists: the default bind is
# localhost, and from the phone "bound to localhost" and "wrong address" look
# identical -- it just cannot connect.
#
#     ./run-phone.sh
#
# Then type the address it prints into the phone app.
set -euo pipefail
cd "$(dirname "$0")"
export HOST=0.0.0.0
echo "Starting on all networks so your phone can reach this computer."
echo "Only do this on a network you trust."
echo
exec ./run.sh "$@"
