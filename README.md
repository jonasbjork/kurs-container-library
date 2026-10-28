# Kurs Container Library

Manifeststyrt bibliotek för `quay.io/kurs`. Innehåller nio **kandidatimages**, inte garanterat färdigverifierade OKD-images. Basimages kommer från Red Hat UBI och SCLorg/CentOS Stream. Alla nio är lokalt Podman-testade för linux/amd64 via QEMU på en ARM64-VM. Inga automatiska publiceringar sker utan uttrycklig aktivering.

## Kom igång

På en Linux-maskin med Podman, Python 3 och PyYAML:

```bash
python3 -m pip install -r requirements.txt
python3 scripts/library.py list
python3 scripts/library.py build --name flask-lab
python3 scripts/library.py test --name flask-lab
```

För att testa allt: `python3 scripts/library.py build` följt av `python3 scripts/library.py test`. Byggen kräver internet. Varje image testas med två godtyckliga UID och GID 0, utan capabilities. Podman-tester garanterar **inte** full OKD-kompatibilitet.

## Publicera till Quay

1. Skapa organisationen `kurs` på Quay.io och de nio repositorierna, eller konfigurera tillåten automatisk repository creation.
2. Skapa ett robotkonto med skrivrättigheter till dessa repositorier.
3. Lägg GitHub Actions secrets `QUAY_USERNAME` och `QUAY_TOKEN` i repot. GitHub Actions finns i `.github/workflows/images.yml`.
4. Kör **Actions → Build, smoke-test and publish → Run workflow**. Välj `candidate` och `publish=true` endast efter uttryckligt godkännande för publicering. Publiceringskommandot testar alla valda images igen och pushar deras testade image-ID:n.
5. `stable` är tekniskt spärrat, även med `ALLOW_PUBLISH=yes`. Det får aktiveras först efter att registryts skydd mot överskrivning har konfigurerats och verifierats. En kontroll av befintligt tag före push räcker inte för att eliminera race conditions. Inga registry-inställningar har ändrats.

Veckoschemat bygger och smoke-testar men **publicerar ingenting**. Därmed går det inte att oavsiktligt ersätta undervisningsimages när upstream ändras.

## Viktiga avgränsningar

- Endast `build`-strategin är implementerad i MVP. `mirror` kan införas i en andra iteration med Skopeo för images som först klarat testmatrisen.
- Bildbaser som använder `latest` kan ändras; lås till digest i produktionsversionen för reproducerbarhet.
- Lokal containerverifiering är genomförd; native amd64 i GitHub Actions och OKD återstår.
- PostgreSQL-test startar en tillfällig databas utan beständig volym.
- CI är konfigurerat för `linux/amd64`; ARM64-images och multiarch är inte verifierade.
- För bättre supply-chain-hantering i nästa iteration: Trivy, SBOM/Syft, digest-lock, licensmetadata och automatiserad förändringsrapport.

## Testa på OKD när tillgängligt

Skapa ett tillfälligt namespace med normal `restricted-v2` SCC och verifiera kandidater med Deployment/Service. `tests/okd-smoke.yaml` är ett exempel. Undvik `anyuid` och `privileged`. Markera resultat separat: `podman-tested` respektive `okd-verified`.

## Källor

- Red Hat: arbitrary UID: https://docs.redhat.com/en/documentation/openshift_container_platform/4.6/html/images/creating-images
- Podman login action: https://github.com/redhat-actions/podman-login
- Skopeo: https://github.com/podman-container-tools/skopeo

## P0: verifiering 2026-10-28

Alla nio images har byggts och smoke-testats med Podman. Status är
**`podman-tested`** för de image-ID:n som finns i
[verifieringsrapporten](tests/results/podman-2026-10-28.json).
Miljö: rootless Podman 6.1.4, Linux/arm64-VM på macOS, linux/amd64-images
körda via QEMU. Detta är inte native amd64-verifiering eller `okd-verified`.
Ingen GitHub Actions-körning har utförts från denna arbetskopia.
Inget har publicerats till Quay och inga registry-inställningar har ändrats.

| Image | Bygg | Smoke, UID 1001230000 | Smoke, UID 1002340000 |
| --- | --- | --- | --- |
| nginx | OK | OK | OK |
| postgresql | OK | OK | OK |
| python | OK | OK | OK |
| network-tools | OK | OK | OK |
| flask-lab | OK | OK | OK |
| mysql | OK | OK | OK |
| mariadb | OK | OK | OK |
| wordpress | OK | OK | OK |
| phpmyadmin | OK | OK | OK |

Körda kontrollkommandon:

```bash
podman info --format '{{.Host.OS}}/{{.Host.Arch}}'
/tmp/kurs-p0-venv/bin/python scripts/library.py list
/tmp/kurs-p0-venv/bin/python -m unittest discover -s tests -v
/tmp/kurs-actionlint/actionlint .github/workflows/images.yml
sh -n images/wordpress/start.sh
sh -n images/phpmyadmin/start.sh
git diff --check
```

Följande två kommandon kördes separat för varje namn i tabellen; misslyckade
byggen/tester rättades och kördes om:

```bash
/tmp/kurs-p0-venv/bin/python scripts/library.py build --name <namn>
/tmp/kurs-p0-venv/bin/python scripts/library.py test --name <namn>
```

Utfall: **16 regressionsprov godkända**, actionlint 1.7.12 utan anmärkning,
båda startskripten syntaxkontrollerade och `git diff --check` utan fel.
Detaljerade bygg-, test- och felsökningsloggar finns lokalt i
`/tmp/kurs-p0-results/` och kan försvinna när temporära filer städas.
JSON-rapporten innehåller lokala image-ID:n, inte publicerade registry-digests.

Korrigerade fel:

- PostgreSQL-referensen `registry.access.redhat.com/ubi9/postgresql-16` saknas.
  Den ersattes av SCLorgs PostgreSQL 16 på CentOS Stream 9, låst till digest.
- UBI saknar paketet `traceroute`; network-tools använder `tracepath` från
  `iputils`. Konflikten mellan `curl-minimal` och `curl` löses explicit med
  DNF `--allowerasing`.
- Rootless Podman behöver en explicit mappning för de höga test-UID:na.
  `--uidmap`/`--gidmap` används med `--passwd=false`, så UID:t inte
  automatiskt läggs in i `/etc/passwd`. GID 0, `--cap-drop=ALL` och
  `no-new-privileges` gäller fortsatt.
- PHP-basens CLI-OPcache hängde/kraschade under QEMU. CLI-cache är avstängd
  i webbapparna; webbserverns OPcache är fortsatt aktiverad.
- PHP-FPM rensade miljövariabler och gav WordPress HTTP 500 trots fungerande
  CLI-SQL. Poolen använder nu `clear_env = no`. phpMyAdmin-testet gör även
  riktig cookie-/CSRF-baserad webbinloggning och kräver synlig kursdatabas.
- WordPress-testet väljer installationssteget `?step=1` för att undvika att
  resultatet beror på tillgängliga språkpaket.

Smoke-testerna har temporära namn, timeout, felloggar och städning vid fel,
SIGTERM och Ctrl-C. Testcontainers, testnätverk och anonyma testvolymer är
städade; befintliga användarresurser har inte tagits bort. SIGKILL kan inte
fångas. Fixture-hämtning görs före resursstart med separat timeout.

Kvar före full P0-verifiering i CI: kör samma matris på en native amd64-runner.
Stable-publicering förblir spärrad tills registryts immutabilitet kan
garanteras. Databastesterna använder tillfällig lagring; beständiga volymer,
återstart med data och OKD-SCC är inte verifierade.

## MySQL, MariaDB, WordPress och phpMyAdmin

Fyra nya kandidater är tillagda. Bibliotekets version `1.0` är en kursversion;
upstream-versionerna anges nedan. De är **Podman-testade**, men inte OKD-verifierade; se rapporten ovan.

| Image | Upstream | Port | Runtime-inställningar |
| --- | --- | --- | --- |
| `mysql` | MySQL 8.4, SCLorg/CentOS Stream 9 | 3306 | `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` |
| `mariadb` | MariaDB 10.11, SCLorg/CentOS Stream 9 | 3306 | `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` |
| `wordpress` | WordPress 6.9.10 på UBI PHP 8.3 | 8080 | `WORDPRESS_DB_HOST`, `WORDPRESS_DB_NAME`, `WORDPRESS_DB_USER`, `WORDPRESS_DB_PASSWORD` |
| `phpmyadmin` | phpMyAdmin 5.2.3 på UBI PHP 8.3 | 8080 | `PMA_HOST`, valfritt `PMA_PORT` (3306) |

Observera att även MariaDB använder `MYSQL_*` enligt SCLorgs gränssnitt.
Databasernas baser är låsta till digest. Webbapparnas versionslåsta arkiv
kontrolleras med SHA256 under bygget; PHP-basen är fortfarande en rörlig tag.
Licenser: MySQL Community GPLv2, MariaDB-server GPLv2, WordPress GPLv2 eller
senare, phpMyAdmin GPLv2 eller senare; inkluderade komponenter har egna licenser.

Bygg och testa separat, eller använd kommandona utan `--name` för hela biblioteket:

```bash
python3 scripts/library.py build --name mysql
python3 scripts/library.py test --name mysql
python3 scripts/library.py build --name mariadb
python3 scripts/library.py test --name mariadb
python3 scripts/library.py build --name wordpress
python3 scripts/library.py test --name wordpress
python3 scripts/library.py build --name phpmyadmin
python3 scripts/library.py test --name phpmyadmin
```

Databastesterna kräver autentiserad TCP-anslutning samt SQL-skrivning/läsning.
Webbapparnas tester startar en isolerad MariaDB-fixture från SCLorg med låst
digest (hämtas vid behov), verifierar PHP/mysqli mot databasen och kontrollerar
WordPress installationsformulär respektive phpMyAdmins webbinloggning med synlig kursdatabas.
Allt körs med två godtyckliga UID, GID 0 och borttagna capabilities.
Fixture, anonyma volymer och tillfälligt nätverk städas efter varje test.
Testerna verifierar inte en färdiginstallerad WordPress eller pluginhantering.

För en lokal labb efter lyckade byggen (sätt först `MYSQL_PASSWORD` i miljön):

```bash
podman network create kurs-lab
podman run -d --name kurs-db --network kurs-lab \
  --uidmap=0:1:65536 --uidmap=1001230000:0:1 --gidmap=0:0:65536 --passwd=false \
  --user 1001230000:0 --cap-drop=ALL --security-opt=no-new-privileges \
  -e MYSQL_USER=kurs -e MYSQL_DATABASE=kurs -e MYSQL_PASSWORD \
  localhost/kurs/mariadb:test
podman run -d --name kurs-wordpress --network kurs-lab \
  --uidmap=0:1:65536 --uidmap=1001230000:0:1 --gidmap=0:0:65536 --passwd=false \
  --user 1001230000:0 --cap-drop=ALL --security-opt=no-new-privileges \
  -p 127.0.0.1:8080:8080 \
  -e WORDPRESS_DB_HOST=kurs-db -e WORDPRESS_DB_NAME=kurs -e WORDPRESS_DB_USER=kurs \
  -e WORDPRESS_DB_PASSWORD="$MYSQL_PASSWORD" localhost/kurs/wordpress:test
podman run -d --name kurs-phpmyadmin --network kurs-lab \
  --uidmap=0:1:65536 --uidmap=1001230000:0:1 --gidmap=0:0:65536 --passwd=false \
  --user 1001230000:0 --cap-drop=ALL --security-opt=no-new-privileges \
  -p 127.0.0.1:8081:8080 -e PMA_HOST=kurs-db localhost/kurs/phpmyadmin:test
```

Vänta tills databasen är redo. Öppna WordPress på `http://localhost:8080` och
phpMyAdmin på `http://localhost:8081` (databasanvändare `kurs` och ditt lösenord).
MySQL kan ersätta MariaDB i exemplet. phpMyAdmin använder cookie-inloggning
och tillåter inte tomt lösenord. Inga databaslösenord byggs in i images.

Labbexemplet använder tillfällig lagring. För beständig drift behöver databasen
lagring på `/var/lib/mysql/data` och WordPress på `/opt/app-root/src/wp-content`,
med rättigheter för valt UID/GID. Volymmontering och återstart med beständiga
data är inte verifierade. WordPress genererar salts vid start; ange beständiga
`WORDPRESS_AUTH_KEY`, `WORDPRESS_SECURE_AUTH_KEY`, `WORDPRESS_LOGGED_IN_KEY`,
`WORDPRESS_NONCE_KEY` och motsvarande fyra `WORDPRESS_*_SALT` för stabila
sessioner mellan omstarter. phpMyAdmin kan få `PMA_BLOWFISH_SECRET` (32 byte);
annars skapas en slumpnyckel vid varje start. Använd Secrets i OKD.

Städa labben:

```bash
podman rm -f --volumes kurs-wordpress kurs-phpmyadmin kurs-db
podman network rm kurs-lab
```

Upstream-källor:

- [SCLorg PostgreSQL](https://github.com/sclorg/postgresql-container)
- [SCLorg MySQL](https://github.com/sclorg/mysql-container) och [MariaDB](https://github.com/sclorg/mariadb-container)
- [SCLorg PHP 8.3](https://github.com/sclorg/s2i-php-container/blob/master/8.3/README.md)
- [WordPress releasearkiv](https://wordpress.org/download/releases/)
- [phpMyAdmin nedladdningar och checksummor](https://www.phpmyadmin.net/downloads/)

Första GitHub Actions-körningen byggde alla nio images men stoppades vid
smoke-start av `keep-id`/GID 0 i runnerns Podman/crun. Testharnessen använder
nu explicita rootless UID/GID-mappningar (kräver 65536 subordinate UID/GID).
Rootful Podman behåller värdens UID/GID-namnrymd och kör med det höga UID:t.
