# Kontrollerade källuppdateringar

`images.yaml` är single source of truth. `source.reference` är den tag som ska
bevakas, `source.digest` låser ett **enskilt linux/amd64-manifest**. En tag eller
ett multiarch-index används aldrig som bygglås. CI ändrar inga lås automatiskt.

1. Kör `python3 scripts/library.py updates`. Granska `reports/upstream-updates.json`.
   Kommandot läser registryt och skriver bara en rapport; det ändrar inte manifest,
   Containerfiles, versioner eller Quay. Vecko- och manuella CI-körningar gör samma sak.
2. Skapa en branch och PR. Kontrollera upstream-release och licenser. Ändra digest
   och källversion i manifestet, uppdatera kursversion om en utgiven version ersätts.
   Redan publicerade kursversioner får inte återanvändas för nytt innehåll.
3. För mirror: den gamla bedömningen gäller bara den gamla digesten. Kör
   `python3 scripts/library.py assess --name <namn>` och granska den nya posten i
   `assessments/`. Assessment är en lokal import följd av två UID-tester; ingen
   registry-skrivning sker. Root-default, annan plattform eller ett testfel stoppar
   godkännande. En ändrad digest kan inte användas som mirror med gammal bedömning.
4. För WordPress/phpMyAdmin: uppdatera `artifact.url`, `artifact.version` och
   `artifact.sha256` tillsammans. Hämta arkivet från projektets officiella källa
   och jämför med publicerad checksumma/signatur när sådan finns.
5. Flask-wheels är låsta med version och SHA256 i image-kontextens requirements.
   Uppdatera även transitiva beroenden och deras linux/amd64/Python 3.12-hashar.
   `pip --require-hashes` stoppar en ofullständig låsning.
6. Kör `validate`, `build`, `verify` och `catalog`. Granska testsvar, Trivy-fynd,
   SBOM och katalogdiff i PR:n. CI använder bara de föreslagna låsen och laddar
   upp rapporterna även vid misslyckad verifiering.
7. Efter granskning kan kandidaten publiceras manuellt med uttryckligt godkännande.
   Publiceringen testar/skannar alla valda image-ID:n igen före första push.
   Stable är fortsatt spärrat tills registry-immutabilitet kan garanteras.

Bygglås gör källvalet spårbart; de garanterar inte byteidentiska byggen. DNF-repon,
byggtidsstämplar och builder-versioner kan fortfarande ändra ett härlett image-ID.
Faktiskt byggda/testade/skannade image-ID:n sparas därför i provenance. Samma
image-ID används för push; registryts returnerade digest knyts till rapporterna.

Mirror kopierar en enda bedömd arkitektur med Skopeo via ett lokalt docker-arkiv.
Konfigurationsdigesten (inklusive rootfs diff-ID:n) måste bevaras. Transporten kan
ändra manifestserialisering/mediatyp; källans digest och resultatets digest hålls
isär. ARM64 och kopiering av hela manifestlistor är avsiktligt inte implementerade.

Den befintliga gröna P0-rapporten beskriver P0-commitens innehåll. Ny käll-digest,
ändrat bygginnehåll eller ändrad manifestpost kräver ny P1-verifiering; katalogen
återanvänder inte en rapport med fel input-fingerprint.

Webbtesternas MariaDB kommer från manifestets lokalt byggda `test_database`,
inte från en fristående rörlig fixture-tag. Ändringar i beroendets bygginnehåll
ändrar också webbimagens input-fingerprint och kräver ny verifiering.
Uppdateringsrapporten bevakar containerreferenser; applikationsarkiv och
Composer-/wheel-lås uppdateras manuellt via PR efter releasegranskning.
