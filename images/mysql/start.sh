#!/bin/sh
set -eu
# Generate a secret at runtime without printing it. Set MYSQL_ROOT_PASSWORD
# explicitly if administrative access must survive a persistent-volume restart.
if [ -z "${MYSQL_ROOT_PASSWORD:-}" ] && [ -z "${MARIADB_ROOT_PASSWORD:-}" ]; then
    MYSQL_ROOT_PASSWORD="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
    export MYSQL_ROOT_PASSWORD
fi
exec /usr/local/bin/docker-entrypoint.sh "$@"
