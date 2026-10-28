# Valfri OKD-verifiering (P2)

P2 är en separat efterhandskontroll av **redan publicerade kandidat-digests**.
Den bygger, pushar eller promoverar inga images. Huvudflödet `images.yml` har
inga beroenden till OKD. Ett otillgängligt kluster ger `pending`, aldrig
`okd-verified`. Publicering till Quay kräver fortfarande uttryckligt godkännande.

## Indata och lokal körning

Hämta `published.digest` och repository från P1:s `publication.json` i den
aktuella publiceringskörningens artifacts. Välj en granskad kandidat, inte en
stable-tagg eller upstream-digest. Skapa en lokal JSON-fil med de images som
ska testas. Ersätt platshållarna med verkliga 64 hextecken:

```json
{
  "mariadb": "quay.io/kurs/mariadb@sha256:<publicerad-manifest-digest>",
  "wordpress": "quay.io/kurs/wordpress@sha256:<publicerad-manifest-digest>",
  "phpmyadmin": "quay.io/kurs/phpmyadmin@sha256:<publicerad-manifest-digest>"
}
```

Bara repositories som motsvarar namnen i `images.yaml` accepteras. Taggar,
manifestindex/multiarch och andra repositories avvisas. Webbappar kräver också
sin `test_database` i samma indatafil. `{}` är tillåtet men ger `pending` med
orsak `no-published-candidates`, utan klusteranrop. Digest i sig bevisar inte
att en release är en granskad kandidat; välj den från publiceringsprovenance.

```bash
python3 scripts/install_tools.py --lock okd-client.lock.json --dest .tools/okd
export PATH="$PWD/.tools/okd:$PATH"
# Logga in separat med normal TLS-validering. Lägg inte tokens i kommandologgar.
# Använd en separat, giltig kubeconfig och kontrollera dess current-context.
KUBECONFIG=/säker/sökväg/kubeconfig python3 scripts/okd.py \
  --candidates /säker/sökväg/candidates.json \
  --output reports/okd/result.json
```

Det krävs Python-beroendena i `requirements.txt`, Skopeo, `oc`, åtkomst till
kandidatregistry och en nåbar OKD-API. Skopeo kontrollerar den låsta manifestets
hash, image config samt `linux/amd64`. Publikt läsbara kandidater stöds direkt.
Privata registryn kräver separat redan konfigurerad läsåtkomst både för Skopeo
och klustrets pull; flödet kopierar inga registrycredentials till klustret.
Använd en oc-version kompatibel med klustrets Kubernetes-version; den medföljande
klienten är låst separat från P1:s scannerverktyg i `okd-client.lock.json`.

## Manuell GitHub Actions-körning

Workflow: `.github/workflows/okd.yml`, **Optional OKD verification**.
Det startas enbart med `workflow_dispatch`, utan schema eller anrop från bygg-CI.

1. Konfigurera GitHub Environment `okd`, gärna med required reviewers.
2. Lägg en dedikerad kubeconfig som environment secret `OKD_KUBECONFIG`.
   Kubeconfig ska ha betrodd CA, giltig inloggning och rätt current-context.
   Den ska inte innehålla beroenden till lokala filer eller interaktiva plugins.
3. Se till att runnern kan nå API:t och att klusternoder kan hämta kandidaterna.
4. Starta workflowet med JSON-objektet i `candidates`.
5. Läs resultatet och ladda ned `okd-result-<run>-<attempt>`.

Workflowet skriver kubeconfig med rättighet 0600 under runnerns temporärkatalog,
ärver ingen annan klusterkonfiguration, och tar bort filen även vid fel.
Saknad secret/utgången inloggning/otillgängligt kluster ger `pending` med exitkod
0; en grön Actions-körning ensam bevisar alltså inte OKD-kompatibilitet.
Kräv `status: pass` och rätt digest i resultatfilen. Testfel ger exitkod 1.
Inga Quay-skrivcredentials används och inga externa inställningar ändras.

Körkontot behöver läsa `clusterversion/version`, skapa/läsa/radera tillfälliga
namespaces samt skapa ServiceAccounts, Secrets, Deployments och Services i dem,
läsa Pods och använda `pods/exec` och `pods/portforward`. Det behöver inte ändra
SCC, RoleBindings eller ClusterRoleBindings. Använd en dedikerad identitet med
avgränsade rättigheter; att skapa/radera namespaces är en klusterbehörighet.
Repositoryt konfigurerar inte dessa externa behörigheter automatiskt.

## Vad som faktiskt testas

- Unikt `kurs-okd-<slump>` namespace med restricted Pod Security Admission.
- Deployment-kontroller skapar Pods med en ny ServiceAccount utan RBAC-grants
  och utan monterad API-token. Detta hindrar körkontots eventuella admin-SCC från
  att avgöra Pod-admission. Inga SCC ändras eller privilegier tilldelas.
- Klustret väljer UID/SELinux från namespacets tilldelning; inget UID, fsGroup
  eller SELinux-värde hårdkodas. Den faktiska `openshift.io/scc` måste vara exakt
  `restricted-v2`; annan SCC ger fail även om appen fungerar.
- `runAsNonRoot`, `allowPrivilegeEscalation: false`, capabilities drop ALL och
  RuntimeDefault seccomp kontrolleras efter admission. Hoståtkomst, hostPath,
  sidocontainers och omstarter avvisas.
- Node selector låser `linux/amd64`. Podens faktiska `imageID` måste matcha det
  låsta registry-manifestet eller dess verifierade config-digest (CRI-O-varianter).
- Startup/readiness-prober, verklig UID, kernelns NoNewPrivs och CapEff, samt
  skapa/läsa/radera fil i imagen avsedd skrivkatalog.
- PostgreSQL/MySQL/MariaDB: autentiserad SQL-skrivning/läsning. Webbappar:
  anslutning till samma testade databas, SQL-skrivning/läsning och HTTP-innehåll.
  phpMyAdmin gör dessutom verklig cookie-/CSRF-inloggning. Python startar en
  HTTP-server explicit; network-tools kontrollerar de förväntade verktygen.
- Beredskap, imageidentitet och säkerhetskontext kontrolleras igen efter test.

Databaslösenord slumpas per körning och läggs i en tillfällig Secret. De finns
inte i Pod-argument, testresultat eller CLI-utskrifter. API-fel och containrars
råa loggar/specifikationer laddas inte upp, eftersom de kan innehålla hemligheter.
Resultatet innehåller säkra felkategorier; undersök klustret lokalt om mer
felsökning behövs. Varje test har begränsad väntetid (`--timeout`, 30–600 sekunder,
standard 300 per image).

## Resultat, städning och katalog

`reports/okd/result.json` innehåller status `pass/fail/pending`, klusterversion,
exakt kandidat-digest, faktisk runtime imageID, UID/SCC/säkerhetskontext,
tidsstämplar, utförda kontroller och hash över testdefinitionen. GitHub-körning och
källkodscommit lagras när de finns. Ingen kubeconfig, token, Secret, full Pod-spec,
serveradress eller rå containerlogg ingår. Filen skrivs som `pending` före test,
så tidigare grönt resultat inte återanvänds vid fel.

Namespace raderas även vid testfel, SIGTERM eller Ctrl-C; ägarmärkningen måste
matcha den aktuella körningen. Borttagningen inväntas. Städningsfel gör hela
resultatet till `fail` och inget märks `okd-verified`. SIGKILL, runnerbortfall och
förlorad klusteråtkomst kan hindra städning; rapporten innehåller namespace-namnet.
En klusteradministratör får då kontrollera ägarmärkning/tid och radera just det
övergivna testnamespacet. Ingen generell prune används.

Spara/hämta resultatet till `reports/okd/result.json` tillsammans med P1:s
publiceringsrapporter och kör `python3 scripts/library.py catalog`.
Katalogen visar `okd-verified` endast om hela körningen och städningen passerat
och resultatets digest exakt motsvarar imagen i matchande `publication.json`.
Ett annat digest, pending eller en lokal Podman-körning räcker inte.
Den fristående resultatfilen bevarar även historiska kandidat-digests.

Detta är ingen CVE-skanning, promotion eller garanti för beständig lagring.
PVC, databasåterstart med bevarade data, Route/TLS, klusteruppgradering och
multiarch omfattas inte. P1:s säkerhetsgrind och spärrade stable-publicering
kvarstår. Inga images är OKD-verifierade förrän ett verkligt test passerat.

Referenser: [OKD:s SCC-admission och förallokerade UID/SELinux-intervall](https://docs.okd.io/latest/authentication/managing-security-context-constraints.html),
[Kubernetes startup- och readiness-prober](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/).
