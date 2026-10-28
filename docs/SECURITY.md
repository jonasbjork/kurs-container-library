# Säkerhetsgrind, SBOM och provenance

`python3 scripts/library.py verify` testar och skannar **exakt lokalt image-ID**.
En matchande byggpost för aktuellt manifest och bygginnehåll krävs. Imagen
exporteras till ett temporärt Docker-arkiv vars config-digest kontrolleras före
verktygskörning. Inget kluster eller publicerat image krävs.

Syft genererar CycloneDX JSON. Trivy söker OS- och applikationssårbarheter. Alla
severity-nivåer och även ofixade fynd finns i JSON-rapporten. Policykoden stoppar
alla `CRITICAL` som saknar ett giltigt undantag. Fynd på övriga nivåer rapporteras
men stoppar inte P1-grinden. Verktygsfel, fel image-ID, trasiga/uteblivna rapporter,
tom SBOM eller misslyckat test ger aldrig godkänt resultat.

Tool-versioner och officiella releasearkivs SHA256 finns i `tools.lock.json`.
`scripts/install_tools.py --dest <katalog>` hämtar enbart dessa arkiv, kontrollerar
hashen och extraherar enbart den namngivna binären. Uppdateringar sker via PR.
Trivys sårbarhetsdatabas hämtas och uppdateras separat; en oförändrad image kan
alltså börja blockeras när ett nytt CVE blir känt. Fel vid DB-hämtning blockerar.
Publik DB-hämtning använder en isolerad tom Docker-config, inte privata credentials.

## Tidsbegränsade undantag

`security/exceptions.yaml` innehåller initialt en tom lista. Inga undantag skapas
automatiskt. Ett undantag måste granskas i PR och innehålla exakt image, CVE,
paketnamn, ansvarig, motivering, HTTPS-länk till uppföljning och slutdatum (högst
90 dagar framåt). Utgångna undantag stoppar verifiering. Jokertecken och generella
ignorera-listor stöds inte. Dokumentera varför fix saknas, verklig exponering och
vilken åtgärd som ska ersätta undantaget. Ett exempel på fält, inte ett aktivt undantag:

```yaml
exceptions:
  - image: <exakt namn>
    cve: CVE-YYYY-NNNNN
    package: <exakt paketnamn från Trivy>
    owner: <ansvarig>
    reason: <konkret motivering och åtgärd>
    tracking: https://<ärende-url>
    expires: 'YYYY-MM-DD'
```

## Rapporter och publicering

`reports/<namn>/` innehåller:

- `build.json`: source-lock, input-fingerprint och lokalt image-ID.
- `verification.json`: smoke-resultat, säkerhetspolicy och SHA256 för rapporterna.
- `sbom.cdx.json`: CycloneDX-SBOM för den exporterade imagen.
- `trivy.json`: skannerns fullständiga sårbarhetsrapport.
- `policy.json`: blockerade och undantagna kritiska fynd samt verktygsversioner.
- `publication.json`: skapas först vid verklig push och innehåller registryts digest,
  samma testade/skannade image-ID och rapporthashar. Digesten återkontrolleras mot
  registry-manifestets config-digest. Ingen sådan post fabriceras vid lokala tester.

CI laddar alltid upp rapporter, lås, bedömningar och genererad katalog som artifact
med 30 dagars retention. Hämta och bevara artifacts med undervisningsreleaser om de
behövs längre. En delvis misslyckad batch fortsätter att verifiera övriga images,
men hela verifieringssteget misslyckas och ingen publicering tillåts.

Publicering kräver manuell start, `publish=true`, main-branch, Quay-secrets och
`ALLOW_PUBLISH=yes`. Alla valda images testas och skannas i publiceringsanropet
innan första push. Stable är tekniskt avstängt. Detta är inte signering, en
reproducerbarhetsgaranti eller en faktisk OKD/SCC-verifiering.

## Konkreta P1-åtgärder

CentOS Stream-baserna stoppades eftersom OS-CVE-scanning saknas. Databaserna
använder nu officiella baser på Alpine, Oracle Linux och Ubuntu. PostgreSQLs
Bookworm-variant hade ofixade kritiska bibliotek och ersattes av Alpine 3.23.
Oanvända privilegiehjälpare och MySQL Shell togs bort. phpMyAdmins medföljande
Twig uppdaterades till 3.30.0 genom ett granskbart Composer-lås. Inga CVE-undantag
har lagts till för att göra matrisen grön. SQL, CMS-installation och webbinloggning
har testats om efter ändringarna. Root-körning är inte ett stött startup-fall.

OS-stöd och en grön kritisk-policy betyder inte att varje tredjepartspaket har
full advisory-täckning. Läs även kvarstående HIGH/MEDIUM/LOW-fynd och respektive
upstream-leverantörs releaseinformation före undervisningsrelease/publicering.
