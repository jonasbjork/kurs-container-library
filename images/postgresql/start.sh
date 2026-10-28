#!/bin/sh
set -eu
export POSTGRES_USER="${POSTGRES_USER:-${POSTGRESQL_USER:-}}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-${POSTGRESQL_PASSWORD:-}}"
export POSTGRES_DB="${POSTGRES_DB:-${POSTGRESQL_DATABASE:-}}"
exec /usr/local/bin/docker-entrypoint.sh "$@"
