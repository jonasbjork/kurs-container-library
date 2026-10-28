#!/bin/sh
set -eu
: "${WORDPRESS_DB_HOST:?Set WORDPRESS_DB_HOST}"
: "${WORDPRESS_DB_NAME:?Set WORDPRESS_DB_NAME}"
: "${WORDPRESS_DB_USER:?Set WORDPRESS_DB_USER}"
: "${WORDPRESS_DB_PASSWORD:?Set WORDPRESS_DB_PASSWORD}"
umask 077
# Secrets are generated at runtime, never baked into the image.
php -r '$keys=["AUTH_KEY","SECURE_AUTH_KEY","LOGGED_IN_KEY","NONCE_KEY","AUTH_SALT","SECURE_AUTH_SALT","LOGGED_IN_SALT","NONCE_SALT"]; $s="<?php\n"; foreach($keys as $key) {$value=getenv("WORDPRESS_".$key) ?: bin2hex(random_bytes(32)); $s.="define(".var_export($key,true).", ".var_export($value,true).");\n";} file_put_contents("/tmp/kurs-wordpress-salts.php",$s);'
exec /usr/libexec/s2i/run
