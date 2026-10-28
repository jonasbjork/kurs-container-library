# Kurs Container Library

Manifeststyrt bibliotek för `quay.io/kurs`. Innehåller nio **kandidatimages**, inte garanterat färdigverifierade OKD-images. Basimages kommer från Red Hat UBI och Docker Official Images (PostgreSQL, MySQL och MariaDB). P0 är verifierat både lokalt och i native amd64-CI. Den slutliga P1-matrisen är lokalt verifierad; se P1-rapporten nedan. Inga automatiska publiceringar sker utan uttrycklig aktivering.

## Kom igång

På Linux med Podman, Skopeo, curl och Python 3 (eller motsvarande Podman-VM):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
source .venv/bin/activate
python3 scripts/install_tools.py --dest .tools/bin
export PATH="$PWD/.tools/bin:$PATH"
python3 scripts/library.py list
python3 scripts/library.py build --name flask-lab
python3 scripts/library.py test --name flask-lab
```

För hela P1-grinden: `python3 scripts/library.py build` följt av `python3 scripts/library.py verify`. `test` kör enbart smoke-tester. Byggen kräver internet. Varje image testas med två godtyckliga UID och GID 0, utan capabilities. Podman-tester garanterar **inte** full OKD-kompatibilitet.

## P1: spårbara källor och säkerhetsgrind

[Genererad katalog](catalog/README.md) och [JSON-katalog](catalog/images.json)
innehåller källor, versioner, licensinformation, plattform, startkommandon och
verifieringsstatus. Schema: `schema/images.schema.json`. Manifestet är single
source of truth även för webbtesternas databasberoende.

```bash
python3 scripts/library.py validate
python3 scripts/library.py build
python3 scripts/library.py verify
python3 scripts/library.py catalog
python3 scripts/library.py updates
```

`verify` kräver Syft/Trivy enligt `tools.lock.json`. Alla kritiska CVE:er blockerar,
även ofixade, om de saknar ett granskat tidsbegränsat undantag. Saknat OS-stöd
blockerar också. SBOM, full Trivy-rapport, policy och provenance sparas under
`reports/<namn>/` och laddas upp som CI-artifacts även vid fel. Scan-resultat är
en tidsstämplad bedömning, inte en garanti att en image saknar sårbarheter.

- [Uppdatera genom PR och granska lås](docs/UPDATES.md)
- [Säkerhetspolicy, undantag, SBOM och publiceringsprovenance](docs/SECURITY.md)

P1:s lokala verifiering finns i [resultatrapporten](tests/results/p1-local-2026-10-28.json): nio images, arton UID-prov, 38 regressionsprov, SBOM och noll kritiska fynd utan undantag. Lägre severity-fynd kvarstår i Trivy-rapporterna. P1 är mergad och [native amd64-CI på main är grön](https://github.com/jonasbjork/kurs-container-library/actions/runs/40776889642).

P1 byter databasernas CentOS Stream-baser: Trivy stöder inte deras OS-familj och
RHEL-alternativen kräver villkorsacceptans/inloggning. De officiella baserna
anpassas med GID 0, högportar och egna runtime-ägda datakataloger. PostgreSQL använder Alpine 3.23, MySQL Oracle Linux 9 och MariaDB Ubuntu 22.04. Oanvända gosu/su-exec är borttagna; images körs som non-root. MySQL Shell, som innehöll en sårbar certifi-kopia, ingår inte; vanliga mysql-klienten finns kvar. SQL-gränssnittet
behålls. För MySQL/MariaDB genererar wrappern ett slumpmässigt root-lösenord vid
start om inget har lämnats, utan att logga det. Ange `MYSQL_ROOT_PASSWORD` själv
om du behöver administrativ åtkomst med beständig lagring.

Python är nu en oförändrad SDK/runtime-mirror. Upstreams standardkommando visar
användningshjälp; ange ditt eget kommando, till exempel:

```bash
podman run --rm -it localhost/kurs/python:test python3
podman run --rm -p 127.0.0.1:8080:8080 localhost/kurs/python:test python3 -m http.server 8080 --bind 0.0.0.0
```

Python-smoke startar HTTP-servern explicit för att testa runtimen under båda UID:n.
phpMyAdmin 5.2.3:s medföljande Twig 3.11.3 blockerades av sex kritiska fynd. Ett
versionslåst produktions-Composer-lås uppdaterar Twig till 3.30.0 och används i
bygget; plugins och Composer-scripts körs inte. Detta är en dokumenterad anpassning
av releasearkivet, inte ett påstående om en ny upstream-release av phpMyAdmin.

## Publicera till Quay

1. Skapa organisationen `kurs` på Quay.io och de nio repositorierna, eller konfigurera tillåten automatisk repository creation.
2. Skapa ett robotkonto med skrivrättigheter till dessa repositorier.
3. Lägg GitHub Actions secrets `QUAY_USERNAME` och `QUAY_TOKEN` i repot. GitHub Actions finns i `.github/workflows/images.yml`.
4. Kör **Actions → Build, smoke-test and publish → Run workflow**. Välj `candidate` och `publish=true` endast efter uttryckligt godkännande för publicering. Publiceringskommandot testar och skannar alla valda images igen och pushar deras exakta image-ID:n. SBOM och CVE-rapporter knyts till registryts returnerade digest.
5. `stable` är tekniskt spärrat, även med `ALLOW_PUBLISH=yes`. Det får aktiveras först efter att registryts skydd mot överskrivning har konfigurerats och verifierats. En kontroll av befintligt tag före push räcker inte för att eliminera race conditions. Inga registry-inställningar har ändrats.

Veckoschemat bygger och smoke-testar men **publicerar ingenting**. Därmed går det inte att oavsiktligt ersätta undervisningsimages när upstream ändras.

## Viktiga avgränsningar

- `build` och `mirror` stöds. Python är en oförändrad, bedömd UBI-mirror; övriga åtta är anpassade byggen.
- Alla byggbaser är låsta till plattformsspecifik digest. Referenstaggar bevakas enbart för uppdateringsrapporter.
- Lokal och native amd64-verifiering i GitHub Actions är genomförd; OKD återstår.
- PostgreSQL-test startar en tillfällig databas utan beständig volym.
- CI är konfigurerat för `linux/amd64`; ARM64-images och multiarch är inte verifierade.
- Trivy, Syft, digest-lock och uppdateringsrapport ingår i P1. Signering och full byte-reproducerbarhet återstår.

## Testa på OKD när tillgängligt

[P2-instruktioner](docs/OKD.md) beskriver det separata manuella workflowet
**Optional OKD verification** och `scripts/okd.py`. Ange redan publicerade
`quay.io/kurs/<namn>@sha256:<digest>` i en JSON-fil; webbappar behöver även sin
databasfixture som digest. Flödet skapar ett tillfälligt namespace, kräver faktisk
`restricted-v2`-admission, testar runtime/HTTP/SQL och städar efteråt.

Resultat i `reports/okd/result.json` och separat CI-artifact anger exakt digest,
klusterversion och `pass/fail/pending`. Saknat kluster eller inga publicerade
kandidater ger `pending`, aldrig `okd-verified`. Huvud-CI är oberoende av OKD.
Katalogen kan koppla ett godkänt resultat till samma publicerade digest.
Ingen image har ännu verifierats på ett verkligt OKD-kluster.

## Källor

- Red Hat: arbitrary UID: https://docs.redhat.com/en/documentation/openshift_container_platform/4.6/html/images/creating-images
- Podman login action: https://github.com/redhat-actions/podman-login
- Skopeo: https://github.com/podman-container-tools/skopeo

## P0: verifiering 2026-10-28

**P0 är verifierat med stable-publicering fortsatt spärrad. Rapporten nedan avser P0-källkoden, inte P1-ändringarnas nya image-ID:n.**
[CI-körning 40711451261](https://github.com/jonasbjork/kurs-container-library/actions/runs/40711451261)
passerade för källkodscommit `2f8313b20fdc88bb9b3329104b65d224b7eef7c6`:
nio byggen, arton UID-smoke-prov och tjugo regressionsprov på Ubuntu 24.04,
native linux/amd64. Quay-inloggning och publicering hoppades över.

Status är **`podman-tested`**, fortfarande inte `okd-verified`.
[CI-rapporten](tests/results/github-actions-2026-10-28.json) innehåller testat
commit, run-URL och runnerns lokala image-ID:n. Den tidigare
[lokala rapporten](tests/results/podman-2026-10-28.json) dokumenterar
QEMU-körningen på Linux/arm64-VM med Podman-server 6.1.0 och macOS-klient 6.1.4.
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

Utfall efter CI-rättningarna: **20 regressionsprov godkända**, actionlint 1.7.12 utan anmärkning,
båda startskripten syntaxkontrollerade och `git diff --check` utan fel.
Detaljerade bygg-, test- och felsökningsloggar finns lokalt i
`/tmp/kurs-p0-results/` och kan försvinna när temporära filer städas.
JSON-rapporterna innehåller lokala image-ID:n, inte publicerade registry-digests.

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
fångas. P0-fixture-hämtning gjordes före resursstart med separat timeout. P1 använder i stället det lokalt byggda manifestberoendet.

Den fullständiga matrisen är nu grön på native amd64 i CI.
Stable-publicering förblir spärrad tills registryts immutabilitet kan
garanteras. Databastesterna använder tillfällig lagring; beständiga volymer,
återstart med data och OKD-SCC är inte verifierade.

## MySQL, MariaDB, WordPress och phpMyAdmin

Fyra nya kandidater är tillagda. Bibliotekets version `1.0` är en kursversion;
upstream-versionerna anges nedan. De är **Podman-testade**, men inte OKD-verifierade; se rapporten ovan.

| Image | Upstream | Port | Runtime-inställningar |
| --- | --- | --- | --- |
| `mysql` | MySQL 8.4, Docker Official Image/Oracle Linux 9 | 3306 | `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` |
| `mariadb` | MariaDB 10.11, Docker Official Image/Ubuntu 22.04 | 3306 | `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` |
| `wordpress` | WordPress 6.9.10 på UBI PHP 8.3 | 8080 | `WORDPRESS_DB_HOST`, `WORDPRESS_DB_NAME`, `WORDPRESS_DB_USER`, `WORDPRESS_DB_PASSWORD` |
| `phpmyadmin` | phpMyAdmin 5.2.3 + Twig 3.30 på UBI PHP 8.3 | 8080 | `PMA_HOST`, valfritt `PMA_PORT` (3306) |

MariaDB behåller `MYSQL_*`-gränssnittet. PostgreSQL stöder både tidigare `POSTGRESQL_*` och upstreams `POSTGRES_*` via en wrapper.
Alla baser är låsta till digest. Webbapparnas versionslåsta arkiv
kontrolleras med SHA256 under bygget; PHP-basen är också låst; Flask har hash-låsta wheels och phpMyAdmin ett granskbart Composer-lås.
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
Webbapparnas tester startar den byggda och fingerprint-matchade MariaDB-imagen som en isolerad fixture, verifierar PHP/mysqli mot databasen och kontrollerar
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
lagring på `/var/lib/mysql/data` för MySQL, `/var/lib/kurs-mariadb/data` för MariaDB och WordPress på `/opt/app-root/src/wp-content`,
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

### P0-historik

Första GitHub Actions-körningen byggde alla nio images men stoppades vid
smoke-start av `keep-id`/GID 0 i runnerns Podman/crun. Testharnessen använder
nu explicita rootless UID/GID-mappningar (kräver 65536 subordinate UID/GID).
Rootful Podman behåller värdens UID/GID-namnrymd och kör med det höga UID:t.

Nästa CI-körning klarade de sju första imagesens samtliga UID-prov men
runnerns Podman saknade `pull --policy`. Fixture-hämtning använder därför
`podman image exists` följt av vanlig `podman pull` när imagen saknas.

P1-CI visade att äldre Podman/Buildah kastar bort rättighetsändringar under
MariaDB-basens ärvda VOLUME. MariaDB använder därför `/var/lib/kurs-mariadb/data`.
Smoke-tester kör en minimal init för signalhantering/reaping, avbryter direkt
vid avslutad service och städar med omedelbar stop-timeout.
