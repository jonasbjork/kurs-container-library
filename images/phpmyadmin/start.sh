#!/bin/sh
set -eu
: "${PMA_HOST:?Set PMA_HOST}"
umask 077
php -r 'file_put_contents("/tmp/kurs-phpmyadmin-secret", getenv("PMA_BLOWFISH_SECRET") ?: random_bytes(32));'
exec /usr/libexec/s2i/run
