# Kursimages

Genererad från images.yaml. Versionsreferenser i Quay är planerade tills publicering anges.
Lokala image-ID:n identifierar testade byggen; de är inte publicerade registry-digests.

| Image | Kursversion | Strategi | Upstream-version | Podman | Säkerhet | OKD |
| --- | --- | --- | --- | --- | --- | --- |
| nginx | 1.0 | build | 9.8 | podman-tested | pass | not-verified |
| postgresql | 1.0 | build | 16 | podman-tested | pass | not-verified |
| python | 1.0 | mirror | 3.12 | podman-tested | pass | not-verified |
| network-tools | 1.0 | build | 9.8 | podman-tested | pass | not-verified |
| flask-lab | 1.0 | build | 3.12 | podman-tested | pass | not-verified |
| mysql | 1.0 | build | 8.4 | podman-tested | pass | not-verified |
| mariadb | 1.0 | build | 10.11 | podman-tested | pass | not-verified |
| wordpress | 1.0 | build | 6.9.10 | podman-tested | pass | not-verified |
| phpmyadmin | 1.0 | build | 5.2.3 | podman-tested | pass | not-verified |

## nginx

En enkel HTTP-server för webb- och nätverkslabbar.

- Källa: [registry.access.redhat.com/ubi9/ubi:latest](https://github.com/nginx/nginx)
- Låst digest: `sha256:c1f105254b12a7cc676508c7e676d37125fc5c330fe2c1ce5a0cd693fa66ce8e`
- Plattform: `linux/amd64`
- Licenser: Various (UBI and RPM component licenses)
- Image-standardkommando: `nginx -g 'daemon off;'`
- Lokalt startanrop: `podman run --rm --platform=linux/amd64 --cap-drop=ALL --security-opt=no-new-privileges -p 127.0.0.1:8080:8080 localhost/kurs/nginx:test`
- Runtime-variabler (sätt i miljön före start): `inga obligatoriska`
- Databas-/appvariabler, nätverk och volymer: se [README](../README.md).
- Testad image: `sha256:7f5454eea50a9783671464221a526f5fd2322d27f7adbdc00bd803cfd515ce70`
- Publicerad referens: `inte publicerad`
- OKD-bevis för exakt publicerad digest: `inte verifierad`

## postgresql

PostgreSQL-databas för SQL-övningar.

- Källa: [docker.io/library/postgres:16-alpine3.23](https://github.com/docker-library/postgres)
- Låst digest: `sha256:40d24790c1cc175f4245cfc730389fbc122f43d9af3f8dc2d4214902920e0899`
- Plattform: `linux/amd64`
- Licenser: PostgreSQL; bundled component licenses
- Image-standardkommando: `postgres`
- Lokalt startanrop: `podman run --rm --platform=linux/amd64 --cap-drop=ALL --security-opt=no-new-privileges -e POSTGRESQL_USER -e POSTGRESQL_PASSWORD -e POSTGRESQL_DATABASE localhost/kurs/postgresql:test`
- Runtime-variabler (sätt i miljön före start): `POSTGRESQL_USER, POSTGRESQL_PASSWORD, POSTGRESQL_DATABASE`
- Databas-/appvariabler, nätverk och volymer: se [README](../README.md).
- Testad image: `sha256:0f1de6e3103530c5ea1e2af0ae1683413e2e0f8c7cdad55a0b6916e8bfd9d8d6`
- Publicerad referens: `inte publicerad`
- OKD-bevis för exakt publicerad digest: `inte verifierad`

## python

Oförändrad UBI Python 3.12-runtime för egna kommandon och programmeringslabbar.

- Källa: [registry.access.redhat.com/ubi9/python-312:latest](https://github.com/sclorg/s2i-python-container)
- Låst digest: `sha256:8cd368d763bf3903917f34f1642023e2b1d5e56e4311343453f75c5d0f50445f`
- Plattform: `linux/amd64`
- Licenser: Python-2.0; bundled component licenses
- Image-standardkommando: `/bin/sh -c '$STI_SCRIPTS_PATH/usage'`
- Lokalt startanrop: `podman run --rm --platform=linux/amd64 --cap-drop=ALL --security-opt=no-new-privileges -it localhost/kurs/python:test python3`
- Runtime-variabler (sätt i miljön före start): `inga obligatoriska`
- Databas-/appvariabler, nätverk och volymer: se [README](../README.md).
- Testad image: `sha256:8859db5624bbfb0c7e83adc8a04f7b0ed608e196b0e269017b81775ad4a6fa40`
- Publicerad referens: `inte publicerad`
- OKD-bevis för exakt publicerad digest: `inte verifierad`

## network-tools

Nätverksdiagnostik med curl, dig, ip, ping, tracepath, jq och ncat.

- Källa: [registry.access.redhat.com/ubi9/ubi:latest](https://catalog.redhat.com/software/containers/ubi9/ubi/615bcf606feffc5384e8452e)
- Låst digest: `sha256:c1f105254b12a7cc676508c7e676d37125fc5c330fe2c1ce5a0cd693fa66ce8e`
- Plattform: `linux/amd64`
- Licenser: Various (UBI and RPM component licenses)
- Image-standardkommando: `/bin/bash`
- Lokalt startanrop: `podman run --rm --platform=linux/amd64 --cap-drop=ALL --security-opt=no-new-privileges -it localhost/kurs/network-tools:test`
- Runtime-variabler (sätt i miljön före start): `inga obligatoriska`
- Databas-/appvariabler, nätverk och volymer: se [README](../README.md).
- Testad image: `sha256:2a0fcec240d47073928d5feacf3568bb2faa2848a2790cb18bacfcc2be4304e6`
- Publicerad referens: `inte publicerad`
- OKD-bevis för exakt publicerad digest: `inte verifierad`

## flask-lab

Flask-övningsapp med JSON-svar och health-endpoint.

- Källa: [registry.access.redhat.com/ubi9/python-312:latest](https://github.com/sclorg/s2i-python-container)
- Låst digest: `sha256:8cd368d763bf3903917f34f1642023e2b1d5e56e4311343453f75c5d0f50445f`
- Plattform: `linux/amd64`
- Licenser: BSD-3-Clause (Flask); bundled component licenses
- Image-standardkommando: `python3 app.py`
- Lokalt startanrop: `podman run --rm --platform=linux/amd64 --cap-drop=ALL --security-opt=no-new-privileges -p 127.0.0.1:8080:8080 localhost/kurs/flask-lab:test`
- Runtime-variabler (sätt i miljön före start): `inga obligatoriska`
- Databas-/appvariabler, nätverk och volymer: se [README](../README.md).
- Testad image: `sha256:4e0de144c2e2acd4e89b7816839e76dc5eed90e3b189ae06ba20c57b6c3f414f`
- Publicerad referens: `inte publicerad`
- OKD-bevis för exakt publicerad digest: `inte verifierad`

## mysql

MySQL-databas för SQL- och webblabbar.

- Källa: [docker.io/library/mysql:8.4](https://github.com/docker-library/mysql)
- Låst digest: `sha256:5cf1e1293ea42e077e6a22114e6773b9aae3bb8f9933a2acd5a9721518ff8f5b`
- Plattform: `linux/amd64`
- Licenser: GPL-2.0-only; bundled component licenses
- Image-standardkommando: `mysqld --datadir=/var/lib/mysql/data --socket=/tmp/mysql.sock --pid-file=/tmp/mysql.pid`
- Lokalt startanrop: `podman run --rm --platform=linux/amd64 --cap-drop=ALL --security-opt=no-new-privileges -e MYSQL_USER -e MYSQL_PASSWORD -e MYSQL_DATABASE localhost/kurs/mysql:test`
- Runtime-variabler (sätt i miljön före start): `MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE`
- Databas-/appvariabler, nätverk och volymer: se [README](../README.md).
- Testad image: `sha256:3979b18e917ab86afdcaffc92b48cd0a357f0e15aa7ad15a8088b7ef0f145622`
- Publicerad referens: `inte publicerad`
- OKD-bevis för exakt publicerad digest: `inte verifierad`

## mariadb

MariaDB-databas för SQL- och webblabbar.

- Källa: [docker.io/library/mariadb:10.11](https://github.com/MariaDB/mariadb-docker)
- Låst digest: `sha256:6c65a843396dc6c78dd0da19eccaa0a91d25d9d26a4c2afcb75010ac3f59f5ea`
- Plattform: `linux/amd64`
- Licenser: GPL-2.0-only; bundled component licenses
- Image-standardkommando: `mariadbd --datadir=/var/lib/kurs-mariadb/data --socket=/tmp/mysql.sock --pid-file=/tmp/mysql.pid`
- Lokalt startanrop: `podman run --rm --platform=linux/amd64 --cap-drop=ALL --security-opt=no-new-privileges -e MYSQL_USER -e MYSQL_PASSWORD -e MYSQL_DATABASE localhost/kurs/mariadb:test`
- Runtime-variabler (sätt i miljön före start): `MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE`
- Databas-/appvariabler, nätverk och volymer: se [README](../README.md).
- Testad image: `sha256:4542a8db183229a8c3cf089b7f0bf59e360a03f8d267580b3a6cb81a44cf1e01`
- Publicerad referens: `inte publicerad`
- OKD-bevis för exakt publicerad digest: `inte verifierad`

## wordpress

WordPress med extern MySQL/MariaDB för CMS-övningar.

- Källa: [registry.access.redhat.com/ubi9/php-83:latest](https://github.com/sclorg/s2i-php-container)
- Låst digest: `sha256:34adf0b75b1f4c1118c452f7415ac350929659649c370c4a47892e129ceb8987`
- Plattform: `linux/amd64`
- Licenser: GPL-2.0-or-later (WordPress); bundled component licenses
- Image-standardkommando: `/usr/local/bin/kurs-wordpress`
- Lokalt startanrop: `podman run --rm --platform=linux/amd64 --cap-drop=ALL --security-opt=no-new-privileges -p 127.0.0.1:8080:8080 -e WORDPRESS_DB_HOST -e WORDPRESS_DB_NAME -e WORDPRESS_DB_USER -e WORDPRESS_DB_PASSWORD localhost/kurs/wordpress:test`
- Runtime-variabler (sätt i miljön före start): `WORDPRESS_DB_HOST, WORDPRESS_DB_NAME, WORDPRESS_DB_USER, WORDPRESS_DB_PASSWORD`
- Databas-/appvariabler, nätverk och volymer: se [README](../README.md).
- Testad image: `sha256:ed3c4052caea80cd4acfd452f0bda0313bc556af6c412068563f499e97ef8261`
- Publicerad referens: `inte publicerad`
- OKD-bevis för exakt publicerad digest: `inte verifierad`

## phpmyadmin

Webbgränssnitt för MySQL/MariaDB med cookie-inloggning.

- Källa: [registry.access.redhat.com/ubi9/php-83:latest](https://github.com/sclorg/s2i-php-container)
- Låst digest: `sha256:34adf0b75b1f4c1118c452f7415ac350929659649c370c4a47892e129ceb8987`
- Plattform: `linux/amd64`
- Licenser: GPL-2.0-or-later (phpMyAdmin); bundled component licenses
- Image-standardkommando: `/usr/local/bin/kurs-phpmyadmin`
- Lokalt startanrop: `podman run --rm --platform=linux/amd64 --cap-drop=ALL --security-opt=no-new-privileges -p 127.0.0.1:8080:8080 -e PMA_HOST localhost/kurs/phpmyadmin:test`
- Runtime-variabler (sätt i miljön före start): `PMA_HOST`
- Databas-/appvariabler, nätverk och volymer: se [README](../README.md).
- Testad image: `sha256:bb44f9a6e76120cfedf38a7bfe4924c340fb8621b9a2ff0819e9b863aa822816`
- Publicerad referens: `inte publicerad`
- OKD-bevis för exakt publicerad digest: `inte verifierad`
