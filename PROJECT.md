# PROJECT.md — Kurs Container Library

## Syfte

Bygg och förvalta ett manifeststyrt bibliotek med containerimages för IT-undervisning. Images ska publiceras under **`quay.io/kurs/<image>:<tag>`** och i möjligaste mån fungera i OKD/OpenShift med standard-SCC (`restricted-v2`), utan `anyuid`, `privileged` eller specialbehörigheter.

Projektet ska vara lätt att underhålla, begripligt för elever och lärare och kunna användas som ett praktiskt exempel på containerbyggning, CI/CD och supply-chain-säkerhet.

**Viktigt:** OKD-klustret är periodvis otillgängligt. Ingen obligatorisk bygg-, test- eller publiceringsprocess får vara beroende av ett tillgängligt OKD-kluster. Lokal/CI-baserad Podman-testning är obligatorisk; OKD-verifiering är separat och valfri.

## Principer och krav

1. **Källa och spårbarhet:** Hämta upstream-images från dokumenterade, betrodda källor (officiella projekt eller distributionsleverantörer). Redovisa upstream-referens, licens när tillämpligt, version och digest. En image på Docker Hub är inte automatiskt olämplig; problemet är ofta antaganden om körning som root och filsystembehörigheter.
2. **Bygg kontra spegling:** Spegla oförändrat endast om upstream-imagen är lämplig och klarar testkraven. Anpassa annars via versionshanterad `Containerfile`. För undervisningsappar används egna källfiler.
3. **Säker standard:** Containers ska klara godtyckligt, icke-root UID, normalt GID 0 enligt OpenShift-modellen; inte kräva capabilities, privilegier eller bindning till portar under 1024. Behörigheter på skrivbara kataloger ska vara explicita. Undvik hemligheter i images.
4. **Oberoende CI:** GitHub Actions + Podman för byggning och funktionstester; Skopeo för framtida mirror-strategi; Quay.io som distributionsregistry.
5. **Verifieringsnivåer:** Håll tydligt isär `podman-tested` (preliminär kompatibilitet) och `okd-verified` (faktiskt testad i OKD med standard-SCC). Marknadsför aldrig första statusen som den andra.
6. **Stabila kursversioner:** Undervisningsmaterial ska kunna peka på versionslåst tag/digest. Automatisk upstream-uppdatering får inte skriva över utgivna stabila versioner. Nya versioner ska först gå via kandidat och tester.
7. **Minsta privilegium:** Quay-robotkonto med avgränsad skrivrättighet; credentials via GitHub Actions Secrets; inga tokens i repository eller loggar.
8. **Arkitekturer:** Börja med `linux/amd64`. Behandla `arm64` och multiarch som separat, explicit verifierat arbete.

## Nuvarande repository och implementation (MVP)

```text
kurs-container-library/
├── .github/workflows/images.yml  # manuellt jobb + veckovis bygg/test
├── images.yaml                   # nio image-definitioner
├── images/
│   ├── nginx/
│   ├── postgresql/
│   ├── python/
│   ├── network-tools/
│   └── flask-lab/
├── scripts/
│   ├── library.py                # list / build / test / publish
│   └── smoke.py                  # Podman smoke tests med två UID
├── tests/okd-smoke.yaml          # exempelmanifest för OKD
├── requirements.txt
└── README.md
```

Nio kandidatimages: `nginx`, `postgresql`, `python`, `network-tools`, `flask-lab`, `mysql`, `mariadb`, `wordpress`, `phpmyadmin` (version `1.0` i nuvarande manifest). Dessa är **inte** produktions- eller OKD-verifierade.

`images.yaml` är single source of truth för namn, version, byggkontext och testtyp. `scripts/library.py` stödjer nu både `build` och `mirror` med plattformsspecifika digest-lås och separat mirror-bedömning. Befintligt veckojobb bygger och smoke-testar men publicerar inte. Manuell publicering kräver `publish=true` och Quay-secrets. `candidate` får körningsspecifikt tag; `stable` är spärrat i CLI tills registry-immutabilitet har verifierats.

## Körning lokalt

Kräver Linux-miljö med Python 3, PyYAML, Podman och nätverksåtkomst till imagekällorna.

```bash
python3 -m pip install -r requirements.txt
python3 scripts/library.py list
python3 scripts/library.py build --name flask-lab
python3 scripts/library.py test --name flask-lab
# bygg/testa alla:
python3 scripts/library.py build
python3 scripts/library.py test
```

Publicering bör i första hand ske via GitHub Actions. För att kunna publicera krävs att Quay-repon finns (eller får skapas), giltig inloggning samt `ALLOW_PUBLISH=yes` vid anrop till `scripts/library.py publish`.

## Kända begränsningar och teknisk skuld

- Samtliga nio images har nu byggts och smoke-testats lokalt för linux/amd64 via QEMU på Linux/arm64. Native amd64 i CI är också godkänt; OKD återstår. Se README och tests/results/github-actions-2026-10-28.json.
- Podman-tester med godtyckligt UID är inte likvärdiga med `restricted-v2`; SCC, seccomp, SELinux, securityContext och klusterspecifika begränsningar måste testas separat.
- Stable-publicering är tekniskt spärrad. Registry-immutabilitet måste konfigureras och verifieras före eventuell aktivering. Inga registry-inställningar har ändrats.
- Manifestet innehåller nu upstream-metadata, digest, plattform, källversion och licenser. Verifieringsstatus och rapporthashar genereras för matchande input-fingerprint.
- Skopeo-mirror, digest-ändringsrapport, Trivy-policy, Syft-SBOM och katalog är implementerade. Signering och notifieringar återstår.
- Basimages är låsta till digest; ändringar tas genom PR. DNF/APK/paketrepon och byggverktyg kan fortfarande hindra byteidentisk reproducerbarhet.
- PostgreSQL:s smoke-test använder tillfällig databas utan beständig lagring. Bedöm testets realism och krav för arbitrary UID.
- Network-tools-image är avsedd för vanlig nätverksdiagnostik; verktyg som `tcpdump` kan kräva capabilities och ska inte få sådana automatiskt.
- CI kör för närvarande bara `linux/amd64`.
- Upstream-byggen, paketnamn och workflow-kompatibilitet behöver valideras i verklig Linux-runner.

## Föreslagen målarkitektur

```text
images.yaml + Containerfiles + applikationskod (Git)
                   |
                   v
      GitHub Actions (oberoende av OKD)
                   |
            resolve/pin source
                   |
       +-----------+-----------+
       |                       |
  mirror (Skopeo)         build (Podman)
       |                       |
       +-----------+-----------+
                   |
       Podman arbitrary-UID-test
       funktionstest + säkerhetstest
                   |
          candidate i Quay
                   |
      [valfri OKD-verifiering]
                   |
       godkänd, versionerad stable
```

En otillgänglig OKD-instans ska resultera i status `not-verified`/`pending`, **inte** blockera bygg/test av kandidater. Besluta explicit om promotion till stable kräver OKD-verifiering för varje imagekategori; standard bör vara att inte märka stable som OKD-verifierad utan faktisk verifikation.

## Prioriterad arbetsplan för Codex

### P0 — Få MVP att fungera säkert

1. Läs `README.md`, `images.yaml`, workflow och samtliga `Containerfile`/testskript. Inventera fel och gör en kort plan innan ändringar.
2. Kör `list`, bygg och testa **varje** image på en Linux-runner med Podman. Fixa Containerfiles, rättigheter, testlogik och eventuella startproblem. Dokumentera vad som faktiskt testats och vad som inte kunnat testas.
3. Gör testerna deterministiska och isolerade; använd temporära namn, tydlig timeout, loggar vid fel, städning även vid avbrott och icke-noll exitkod vid fel. Se över `smoke.py` så att testkommandon inte kan ge falskt gröna resultat.
4. Hindra tekniskt överskrivning av publicerade stable-taggar, helst även med Quay-inställning för tag-immutabilitet om stödet finns. Kontrollera befintligt tag/digest innan push och hantera race conditions så gott det går. Förhindra publicering av images som inte klarat teststegen i samma körning.
5. Säkerställ att workflow YAML tolkas korrekt av GitHub Actions och att permissions, hemligheter och manuella val är säkra.

**Klart när:** alla fem images kan byggas och smoke-testas i CI, och ett misslyckat test blockerar publicering; stable-tag kan inte oavsiktligt ersättas.

### P1 — Bygg biblioteket som produkt

1. Inför manifestvalidering och tydligt schema för `build` och `mirror` samt `source`, `digest`, plattform, beskrivning, licens, test och version.
2. Implementera `strategy: mirror` med Skopeo. Undvik att spegla en image innan kompatibilitetsbedömning/test; hantera manifestlistor och stöd för flera arkitekturer explicit.
3. Dokumentera och lås upstream-digests. Inför kontrollerade uppdateringar via PR eller annan granskningsbar mekanism; automatiken får inte tyst uppgradera undervisningsversioner.
4. Lägg till Trivy (policy för kritiska CVE med möjlighet till dokumenterat undantag) och SBOM-generering med Syft eller likvärdigt verktyg. Spara rapporter som CI-artifacts och koppla dem till publicerad digest.
5. Skapa maskinläsbar och Markdown-baserad katalog med image, version, källa, användningsfall, startkommando och verifieringsstatus.

**Klart när:** manifestet styr både spegling och byggning, varje image har spårbar provenance och en kontrollerad uppdateringsväg.

### P2 — Valfri OKD-verifiering

1. Lägg till manuellt startbar eller separat pipeline som testar publicerade kandidat-digests på ett tillgängligt OKD-kluster. Inga beroenden från huvud-pipelinen.
2. Använd tillfälligt namespace och standard-SCC; använd inte `anyuid`/`privileged` för att få tester att gå igenom.
3. Testa verklig startup, HTTP-/databasfunktionalitet, filbehörigheter, restricted securityContext och eventuella readiness-probes. Städa resurser efteråt.
4. Publicera/lagra verifieringsresultat med klusterversion, image-digest, tidpunkt och `pass/fail/pending`, utan att exponera kubeconfig eller andra hemligheter.

**Klart när:** det går att OKD-verifiera en redan publicerad kandidat i efterhand och se exakt vilken digest som testats.

### P3 — Pedagogisk katalog och expansion

1. Generera en enkel katalog (Markdown eller statisk webbplats) för elever och kursledare.
2. Utöka biblioteket med omsorgsfullt valda images för Linux, nätverk, databaser, Python, Kubernetes och OpenShift-labbar.
3. Lägg till exempel för Pod, Deployment, Service och Route; var tydlig med vilka labbar som kräver kluster och vilka som fungerar lokalt.
4. Utvärdera `arm64` och multiarch efter att `amd64` är stabilt.

## Kodregler för Codex

- Gör små, granskningsbara ändringar. Behåll enkel Python + YAML om ingen stark anledning finns att byta.
- Återanvänd befintlig struktur och CLI om möjligt; uppdatera README och manifest när beteendet ändras.
- Lägg till tester för manifestparsning, publiceringsskydd, felaktiga konfigurationer och smoke-test-resultat.
- Kör inga riktiga pushes till `quay.io/kurs` och ändra inga externa registry-inställningar utan uttryckligt godkännande. Använd dry-run/mock för utveckling.
- Hårdkoda inte credentials, tokens eller personliga adresser.
- Ange alltid vad som är verifierat genom körning respektive kvarstår som antagande.
- Prioritera pedagogisk enkelhet och korrekt säkerhetsmodell framför avancerad automation.

## Önskad leverans från Codex vid varje iteration

- Kort sammanfattning av ändrade filer och motiv.
- Exakta kommandon som körts och testutfall.
- Kvarstående risker/begränsningar.
- Uppdaterad `README.md` och vid behov `images.yaml`.

## Direkt startuppgift till Codex

> Läs `PROJECT.md` och hela repot. Genomför P0: verifiera/åtgärda bygg och smoke tests för samtliga fem images, stärk publiceringsskyddet för stable, kontrollera GitHub Actions-workflow och dokumentera resultaten. Publicera ingenting till Quay förrän jag uttryckligen godkänner det.

## Utökning beställd 2026-10-28

Utöver de ursprungliga fem kandidaterna ingår nu `mysql` (8.4), `mariadb`
(10.11), `wordpress` (6.9.10) och `phpmyadmin` (5.2.3). Manifest och CI omfattar
nio images. Databasbaserna kommer från SCLorg/CentOS Stream 9; webbapparna
använder UBI PHP 8.3. Alla nio kandidater har nu faktisk lokal Podman-verifiering via QEMU för amd64;
även native amd64 i CI är godkänt; OKD återstår. Se README för teststatus, upstream-källor och labbexempel.
Publiceringsförbudet utan uttryckligt godkännande kvarstår.

## P0-körning efter återställd Podman, 2026-10-28

Nio byggen och arton UID-smoke-prov godkända. Sexton Python-regressionsprov
passerar och workflowet passerar actionlint 1.7.12. Rättade fel omfattar saknad
PostgreSQL-bas, UBI-paket, rootless UID-mappning, CLI-OPcache under QEMU och
PHP-FPM:s miljövariabler. phpMyAdmin testas nu med verklig webbinloggning.
Exakta kommandon, begränsningar och lokala image-ID:n finns i README och
`tests/results/podman-2026-10-28.json`. Inget har publicerats till Quay.

## P0 godkänt i GitHub Actions, 2026-10-28

P0:s bygg-, test- och publiceringsskydd är verifierade för källkodscommit
`2f8313b20fdc88bb9b3329104b65d224b7eef7c6` i
https://github.com/jonasbjork/kurs-container-library/actions/runs/40711451261.
Alla nio byggen, arton UID-prov och tjugo regressionsprov passerar på native
linux/amd64. Två CI-kompatibilitetsfel rättades: keep-id/GID 0 ersattes av
explicita UID/GID-mappningar och pull --policy ersattes av image exists + pull.
Rapport: `tests/results/github-actions-2026-10-28.json`.
Stable-publicering är fortsatt tekniskt spärrad. Quay-stegen hoppades över;
ingen publicering eller ändring av registry-inställningar har utförts.
OKD och beständig lagring återstår som separat verifiering.

## P1 genomförande, 2026-10-28

Manifest med JSON Schema, explicita amd64-lås, källa/version/licens och
kontrollerad PR-uppdateringsväg är implementerat. Python är en bedömd oförändrad
UBI-mirror via Skopeo; åtta images byggs. Databaserna är non-root-anpassningar av
Docker Official Images på skanningsbara OS. CentOS Stream blockerades korrekt
av säkerhetsgrinden. Kritiska fynd åtgärdades genom bas-/beroendeval och borttagna
oanvända verktyg, inte undantag. phpMyAdmin har hash-låst Composer och Twig 3.30.

Lokal P1-verifiering: nio byggen/mirrors, arton UID-prov, 38 regressionsprov,
Syft-SBOM och Trivy-policy med noll kritiska fynd och inga undantag. Rapport:
`tests/results/p1-local-2026-10-28.json`. Katalog: `catalog/README.md` och
`catalog/images.json`. CI laddar upp provenance, SBOM, CVE-rapporter och katalog
även vid fel. Publicering kräver ny test/skanning i samma CLI-anrop och knyter
rapporterna till faktisk registry-digest. Ingen Quay-publicering har utförts.
Native amd64-CI för P1 verifieras i implementerings-PR:n. OKD är fortsatt P2.
