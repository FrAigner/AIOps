# Observability-PoC mit automatisierter Problemerkennung

Lokaler Proof of Concept: OpenTelemetry-Pipeline plus AIOps-Dashboards für eine
simulierte Handelslandschaft – Onlineshop und stationäre Filiale – komplett per
Docker Compose auf macOS.

**Voraussetzung fuer den KI-Chat:** ein kostenloser API-Key von
[console.groq.com/keys](https://console.groq.com/keys), eingetragen in eine
lokale `.env`-Datei (Vorlage: `.env.example`):

```bash
cp .env.example .env
# GROQ_API_KEY=... in .env eintragen
docker compose up -d --build
```

Ohne Key startet der Rest der Plattform trotzdem normal, nur der Chat unter
Port 8090 antwortet dann mit einem Konfigurationshinweis statt einer Analyse.

Grafana läuft danach auf <http://localhost:3000> (anonymer Zugang, keine
Anmeldung). Zwei Dashboards im Ordner **AIOps**:

| Dashboard | Inhalt |
|---|---|
| **AIOps Control Center – Onlineshop** | 24/7-Shop: Suche, Warenkorb, Checkout, Zahlung, Versand |
| **AIOps Control Center – Filialbetrieb** | Kasse, Filiallager, Zentrallager/WMS, Nachschub, Logistik, Gebäudetechnik |

Zwei Lastgeneratoren laufen mit, die Dashboards sind also ohne Zutun gefüllt.

## Die simulierte Landschaft

Beide Anwendungen erzeugen eine mehrstufige Microservice-Topologie mit rund
**60 Knoten und 70 Abhängigkeiten**. Jeder simulierte Service hat eine eigene
`service.name`-Resource, es entstehen also echte Client/Server-Span-Paare – Tempo
leitet daraus die Service-Landkarte ab, ohne dass irgendwo eine Topologie
gepflegt werden müsste.

```
                    ┌─────────── user ───────────┐
                    ▼                            ▼
               poc-api (Shop)  ◄──────────  store-api (Filiale)
                    │            Click&Collect        │
   catalog · search · cart · pricing · promotion      │  pos · receipt · returns
   inventory · fraud · payment · ledger · order       │  store-inventory · wms
   shipping · loyalty · recommendation · ml           │  pick-pack · logistics
                    │                                 │  demand-forecast · esl
        product-db · redis · elasticsearch ·          │  energy · staff
        order-db · warehouse-db · psp · carrier       │  card-terminal · fiskal
                                                      │  robotics · telematics
```

`pricing-service`, `loyalty-service` und `payment-service` werden von beiden
Welten genutzt, und Click & Collect ruft den Onlineshop **echt per HTTP** auf.
Dieser Aufruf propagiert den `traceparent`, ein Trace läuft also über beide
Anwendungen hinweg.

### Tagesrhythmus

Die Last folgt der Uhrzeit – das ist wichtig, damit sichtbar wird, dass die
Anomalieerkennung den normalen Rhythmus nicht mit einer Störung verwechselt.

- **Onlineshop:** rund um die Uhr, nachts schwach, Mittagsspitze, kräftiger
  Abendpeak zwischen 18 und 20 Uhr, Wochenende +20 %. Nachts wird gestöbert,
  abends verschiebt sich der Mix Richtung Warenkorb und Checkout.
- **Filiale:** Öffnungszeiten 7–20 Uhr, sonntags geschlossen. Nachts läuft nur
  Nachschub, Disposition und Inventur, ab 6 Uhr der Wareneingang, tagsüber die
  Kasse mit Mittags- und Feierabendspitze, samstags am stärksten.

Für eine Vorführung lässt sich der Tag zusammenstauchen – in
`docker-compose.yml` bei beiden Lastgeneratoren:

```yaml
- LOADGEN_DAY_SECONDS=1800   # 24 Stunden in 30 Minuten
```

## Architektur

```
poc-api   ──┐
store-api ──┼── OTLP/HTTP:4318 ──> otel-collector ─┬─ prometheusremotewrite ─> VictoriaMetrics
loadgen   ──┘                                      ├─ otlphttp ──────────────> Loki
                                                   └─ otlp/gRPC ─────────────> Tempo
                                                                                 │
VictoriaMetrics <── remote_write ── Tempo metrics_generator ──────────────────────┘
      │
      ├─> vmalert (Recording Rules, Anomalieerkennung, Alerts) ──> Alertmanager
      ├─> ml-anomaly (MSTL-Zeitreihenzerlegung) ──> schreibt ml:*-Vorhersagen zurueck
      ├─> ai-analyst (Chat, liest VM/Loki/Tempo/vmalert) ──> Groq (kostenlose Cloud-LLM-API)
      └─> Grafana (Metriken, Logs, Traces, Service-Landkarte)
```

| Dienst | Port | Zweck |
|---|---|---|
| poc-api | 8000 | Onlineshop (instrumentiert) |
| store-api | 8001 | Filialbetrieb (instrumentiert) |
| Grafana | 3000 | Dashboards |
| VictoriaMetrics | 8428 | Metrik-Backend |
| Loki | 3100 | Log-Backend |
| Tempo | 3200 | Trace-Backend |
| vmalert | 8880 | Regelauswertung |
| Alertmanager | 9093 | Alarm-Zustellung |
| otel-collector | 4317/4318 | OTLP-Eingang (gRPC / HTTP) |
| **ai-analyst** | **8090** | **KI-Analyse-Chat** (siehe unten) |

## Demo-Ablauf

**1. Ausgangslage zeigen** – Health Score grün, Verfügbarkeit über dem SLO-Ziel
von 99,5 %, und in der Konzern-Landkarte die vollständige, automatisch entdeckte
Topologie beider Anwendungen.

**2. Störung auslösen:**

```bash
curl -XPOST localhost:8000/chaos/latency
```

Onlineshop (Port 8000):

| Szenario | Wirkung | Erwarteter Alarm |
|---|---|---|
| `latency` | Payment-Provider ~900 ms langsamer | `LatencyAnomalyDetected`, `DependencyDegraded` |
| `errors` | Warehouse-DB fällt zu 30 % aus | `HighErrorRate`, `ErrorBudgetBurnFast` |
| `search-degraded` | Elasticsearch überlastet | `LatencyAnomalyDetected`, `DependencyDegraded` |
| `ml-degraded` | ML-Inferenz läuft ins Timeout | `LatencyAnomalyDetected` |
| `outage` | Zahlungsstrecke zu 75 % tot | alle oben genannten |

Filiale (Port 8001):

| Szenario | Wirkung |
|---|---|
| `terminal-down` | Kartenterminals gestört – Kassenvorgänge brechen ab |
| `wms-degraded` | Lagerverwaltung und Robotik überlastet |
| `fiscal-outage` | Fiskalschnittstelle nicht erreichbar – kein Bon |
| `logistics-delay` | Routenoptimierung antwortet nicht |

Zurück jeweils mit `curl -XPOST localhost:<port>/chaos/normal`.

**3. Erkennung beobachten** – nach etwa 60–90 Sekunden schlägt der Anomalie-Score
aus, die Alarm-Historie färbt sich, und der Balken „Langsamste Systeme" zeigt
direkt auf den Verursacher.

**4. Beweiskette gehen** – im Panel „Fehlgeschlagene Traces" einen Trace öffnen,
die Span-Hierarchie bis zum langsamen Downstream aufklappen und über „Logs für
diesen Span" in die zugehörigen Logzeilen springen. Umgekehrt führt in jeder
Logzeile der Link „Trace öffnen" zurück in den Trace.

## Wie die Problemerkennung arbeitet

Die Regeln liegen in [`config/vmalert-rules.yaml`](config/vmalert-rules.yaml) und
sind in drei Stufen aufgebaut. Alle SLIs werden **je Anwendung** (`job`)
berechnet, Shop und Filiale haben also getrennte SLOs.

1. **Recording Rules** verdichten die Rohmetriken zu SLIs
   (`poc:error_ratio:5m`, `poc:latency_p95:5m`, `poc:dependency_p95:5m` …). Sie
   werden über `-remoteWrite.url` zurück nach VictoriaMetrics geschrieben und
   sind damit auch im Dashboard direkt abfragbar.

2. **Baseline und Z-Score** – statt fester Schwellwerte vergleicht die Plattform
   die aktuelle Latenz mit ihrem eigenen gleitenden Mittel und normiert die
   Abweichung auf Standardabweichungen. Das Lernfenster ist bewusst um fünf
   Minuten nach hinten versetzt: sonst frisst eine laufende Störung ihre eigene
   Baseline auf und der Alarm löst sich selbst wieder auf.

3. **Alerts** – neben dem Anomalie-Detektor laufen ein SLO-Burn-Rate-Alarm nach
   dem Google-SRE-Muster (14,4-facher Budgetverbrauch), ein Verursacher-Hinweis
   je Downstream-System und eine Traffic-Abriss-Erkennung.

Der **Health Score** gewichtet Fehlerrate (60 %) und Latenz-Anomaliegrad (40 %)
zu einer Zahl von 0 bis 100 – gedacht als Kennzahl für die Management-Sicht,
nicht als Betriebswerkzeug.

Die **RED-Kennzahlen je Service** und die Service-Landkarte stammen nicht aus dem
Code, sondern werden von Tempos `metrics_generator` aus den Traces abgeleitet.
Ein neuer Service taucht dort auf, sobald er das erste Mal aufgerufen wird.

### „Lernt" das System, und werden die Alarme weniger?

Ursprünglich nein – der erste Ausbau war ein reines **gleitendes Zeitfenster**:
alle 15 Sekunden neu berechnete Mittelwert und Streuung der letzten 15 Minuten.
Das passt sich dem *aktuellen* Niveau an, sammelt aber kein Wissen über Tage.
Ein Shop mit Faktor 12 Unterschied im Traffic zwischen 05:00 und 14:00 lässt
sich damit grundsätzlich nicht bewerten: Der Traffic verdreifacht sich jeden
Morgen innerhalb einer Stunde, völlig regulär. Ein Schwellwert auf diesem
Fenster würde entweder jeden Morgen Fehlalarm schlagen oder nachts, wenn der
Shop de facto steht, gar nichts merken.

Deshalb kam ein zweites, langsameres Gedächtnis dazu: ein **saisonales
Tagesprofil**. Es vergleicht die aktuelle Uhrzeit mit derselben Uhrzeit an bis
zu vier Referenztagen (gestern, vorgestern, vor drei Tagen, vor einer Woche) und
mittelt darüber – Tage mit laufendem Alarm werden dabei ausgeklammert, aus
demselben Grund wie beim kurzen Fenster: eine Störung soll nicht zum Maßstab
für morgen werden.

```
avg by (job) (
  label_set(avg_over_time((poc:requests:rate5m
    unless on(job) (count by (job) (ALERTS{alertstate="firing"})))[30m:1m] offset 23h45m), "lag", "1d")
  or label_set(... offset 47h45m ..., "lag", "2d")
  or label_set(... offset 71h45m ..., "lag", "3d")
  or label_set(... offset 167h45m ..., "lag", "7d")
)
```

Jeder Lag wird per `label_set` unterscheidbar gemacht, `or` vereinigt sie zu
einer Menge, `avg by (job)` mittelt über genau die, die tatsächlich Daten haben.
Das ist der Mechanismus, der wirklich lernt: Am ersten Tag trägt nur der
1-Tages-Lag bei, nach einer Woche alle vier – ohne dass jemand etwas umstellt.
Sichtbar im Dashboard als **„Gelernte Vergleichstage"** (0 bis 4).

Die Latenz-Baseline greift jetzt bevorzugt auf dieses Profil zurück und fällt
erst auf das alte gleitende Fenster zurück, wenn dafür noch keine Historie da
ist – der Detektor wird dadurch nie schlechter als vorher, nur präziser.

Frisch gestartet hätte das Profil erst nach einer Woche Echtbetrieb volle
Genauigkeit. Für die Demo trägt [`scripts/seed-history.py`](scripts/seed-history.py)
deshalb einmalig acht Vergleichstage rückwirkend nach – kalibriert am tatsächlich
gemessenen Betrieb, nicht frei erfunden (Details im Skript-Docstring). Das
ersetzt keine echte Historie, sondern überbrückt die Anlaufzeit; VictoriaMetrics
läuft jetzt mit `-retentionPeriod=30d` und einem benannten Volume, damit echte
Betriebstage diesen Seed nach und nach ablösen, statt bei jedem
`--force-recreate` verloren zu gehen.

Alarme werden dadurch **nicht von selbst weniger**. Sie werden weniger, wenn die
Schwelle richtig sitzt. Und genau da lag anfangs ein Fehler:

| Z-Score im Normalbetrieb (2 h gemessen) | Wert |
|---|---|
| Median | −0,5 |
| 95. Perzentil | 5,5 |
| 99. Perzentil | 58,7 |

Die ursprüngliche Schwelle von 3 Sigma lag *unterhalb* des normalen Rauschens
dieses Workloads – jedes zwanzigste Messintervall hätte ausgelöst. Ein Backtest
über zwei Stunden echten Normalbetrieb:

| Regel | Auslösungen |
|---|---|
| `zscore > 3` (alt) | 10,4 % der Intervalle |
| `zscore > 8` + Relevanzbedingungen (neu) | 0,0 % |

Statistische Signifikanz allein reicht nicht. Der Alarm verlangt jetzt drei
Dinge gleichzeitig: einen deutlichen Sigma-Ausschlag, eine real spürbare
Verschlechterung (Faktor 1,75 zur Baseline) und einen absolut relevanten Wert
(über 700 ms). Die 700 ms sind gemessen, nicht geschätzt: im Normalbetrieb
erreicht P95 Spitzen bis 573 ms, die Störungsszenarien liegen bei 1200–1900 ms.

### Drei Detektoren statt einem

Beim Nachmessen kam ein zweiter Fund dazu. Während einer laufenden Störung der
Zahlungsstrecke lag `/api/checkout` bei **2425 ms** – der aggregierte P95 über
alle Endpunkte blieb aber bei **248 ms**. Grund: nachts sind nur gut 3 % der
Requests Checkouts, ein 95. Perzentil über alles sieht diese Population gar
nicht.

Deshalb arbeiten drei Ebenen nebeneinander, mit unterschiedlicher Aufgabe:

| Detektor | Sieht | Verfahren |
|---|---|---|
| `DependencyDegraded` | Welches Downstream-System der Verursacher ist | fester Schwellwert |
| `RouteLatencyAnomaly` | Einzelner Endpunkt fällt aus seinem Rahmen – auch bei geringem Traffic-Anteil | Baseline je Endpunkt |
| `LatencyAnomalyDetected` | Die Anwendung als Ganzes ist betroffen | Baseline gesamt |

Bei der oben beschriebenen Störung hat `DependencyDegraded` korrekt auf
`payment-provider-psp` gezeigt, obwohl der Gesamt-P95 nichts meldete. Das ist
der eigentliche Wert der Trace-basierten Kennzahlen: sie hängen nicht am
Aggregat über alle Requests.

**Gemessener Erkennungslauf** – bewusst als vierte Störung innerhalb von
anderthalb Stunden ausgelöst, also genau das Szenario, an dem die ungemaskte
Baseline vorher gescheitert ist:

```
Ruhezustand   : keine Alarme, Ist 545 ms, Baseline 614 ms, Z-Score -0,6
Störung ausgelöst (chaos/latency)
  nach 142 s  : DependencyDegraded   -> payment-provider-psp
  nach 465 s  : RouteLatencyAnomaly  -> /api/checkout
Ist           : 1439 ms
Baseline      :  614 ms   <- unverändert, die Störung wurde nicht gelernt
Z-Score       : 7,9
Gesamt-P95    :  249 ms   <- der blinde Fleck, meldet weiterhin nichts
```

### Was das saisonale Profil sieht, das die anderen drei nicht sehen

Alle bisherigen Detektoren hängen an Latenz oder Fehlerrate. Es gibt einen
Ausfall, den beide nicht bemerken: ein Ingress, der keinen Traffic mehr
durchlässt. Fehlerrate ist dann null (es gibt keine Requests, die fehlschlagen
könnten), Latenz ist unauffällig, `NoTrafficReceived` würde zwar irgendwann
greifen, kennt aber keine Tageszeit – 0,05 req/s ist um 14 Uhr eine Katastrophe
und um 4 Uhr nachts der Normalzustand mit weitem Sicherheitsabstand.

Deshalb vier neue, auf dem Tagesprofil aufbauende Alarme:

| Alarm | Bedingung | Bedeutung |
|---|---|---|
| `TrafficBelowProfile` | Traffic < 50 % der Erwartung, 5 min | technischer Ausfall, den Fehlerrate/Latenz nicht sehen |
| `TrafficAboveProfile` | Traffic > 250 % der Erwartung, 5 min | Retry-Sturm, Bot-Welle, fehlgeplanter Batch |
| `OrderVolumeAnomaly` | Bestellungen (Shop) < 40 % der Erwartung, 10 min | der Alarm, den das Management versteht: Umsatzausfall statt Millisekunden |
| `POSVolumeAnomaly` | Kassenvorgänge (Filiale) < 40 % der Erwartung, 10 min | dasselbe Prinzip für die Filiale – Kassen nehmen keine Vorgänge mehr an |

Verifiziert durch echten Ausfall der Last (Lastgenerator-Container gestoppt,
nicht nur Fehler simuliert – Traffic bricht auf null ab):

```
Vorher (15:19 UTC)
  Traffic 0,79x, Bestellungen 0,89x der Erwartung, Fehlerrate 0,6 %, keine Alarme

Lastgenerator gestoppt (15:20:43 UTC) - simulierter Ingress-Ausfall
  TrafficBelowProfile : 556 s (rund 9 Minuten 16 Sekunden) bis zum Feuern -
                         danach durchgehend aktiv
  OrderVolumeAnomaly   : lief korrekt in "pending" (ab 15:24:30 UTC, also
                         rund 4 Minuten nach dem Ausfall), hielt die volle
                         Wartezeit durch - bestätigte aber knapp nicht, weil
                         der Lastgenerator im Testablauf versehentlich schon
                         bei 15:31:06 UTC neu gestartet wurde, 3 Minuten vor
                         Ablauf der 10-Minuten-Frist (Feuern wäre 15:34:30
                         UTC fällig gewesen). Der Bestell-Anteil erholte sich
                         daraufhin auf 0,60x und der Alarm löste sich - korrekt,
                         denn die Störung war zu dem Zeitpunkt ja tatsächlich
                         vorbei.
  Fehlerrate nach 9 Minuten Ausfall : 0,6 % - unverändert, de facto 0 relevante
                         Fehler (die paar Prozent sind Hintergrundrauschen der
                         Simulation, kein Symptom des Traffic-Ausfalls)
  P95 nach 9 Minuten Ausfall        : 526 ms - unauffällig, wie erwartet: die
                         wenigen verbleibenden Requests sind technisch normal,
                         das Problem ist die fehlende Menge, nicht ihre Güte
```

Das ist kein geschöntes Ergebnis: `TrafficBelowProfile` ist der Alarm, der in
der Praxis zählt (schneller, technisch), und der hat sauber funktioniert.
`OrderVolumeAnomaly` hat sein Verhalten – 10 Minuten lang korrekt "pending"
bleiben, dann bei echter Erholung korrekt wieder abklingen – ebenfalls bewiesen,
nur die letzte Bestätigung des tatsächlichen Feuerns fiel dem eigenen
Testablauf zum Opfer. Ein sauberer erneuter Lauf ohne den vorzeitigen Neustart
würde ihn zeigen; das wurde hier bewusst nicht wiederholt, um nicht erneut
15 Minuten Last zu unterbrechen.

Alle vier Regeln greifen erst, wenn `poc:learning:profile_days > 0` – ohne
gelernte Vergleichstage wird nicht geraten, der Alarm bleibt stumm statt einen
Fehlalarm auf Verdacht zu schlagen.

### Der wichtigste Fund: eine Störung darf nicht zum neuen Normal werden

Beim wiederholten Auslösen derselben Störung kam das Verfahren ins Straucheln –
und zwar auf eine Art, die in einem echten Betrieb gefährlich wäre:

| Zeit | Ist | Baseline | Faktor | Alarm? |
|---|---|---|---|---|
| 07:05 | 1270 ms | 678 ms | 1,87 | ja |
| 07:20 | 1151 ms | 1009 ms | 1,14 | **nein** |
| 07:30 | 1446 ms | 992 ms | 1,46 | **nein** |

Drei Störungen in 45 Minuten – und die Baseline hatte gelernt, dass 1000 ms
normal sind. Der Detektor schwieg, obwohl das Problem noch da war. Das ist die
eingebaute Schwäche jeder gleitenden Baseline: sie frisst ihre eigene Störung
auf. Ein Wechsel auf robustere Statistik (Median statt Mittelwert) hilft dabei
nicht – war die Störung länger als die Hälfte des Lernfensters aktiv, kippt auch
der Median.

Der Fix ist prinzipieller Natur: **während eines Alarms wird nicht gelernt.**
Die Baseline mittelt nur über Zeiträume, in denen kein Alarm aktiv war:

```
avg_over_time((poc:route_latency_avg:5m
  unless on(job) (count by (job) (ALERTS{alertstate="firing"})))[1h:1m] offset 5m)
```

Wirkung an genau diesen Daten gemessen: **614 ms statt 1006 ms** – obwohl in der
betrachteten Stunde nur 21,7 % der Zeit alarmfrei waren.

Die Maske steht bewusst inline in der Subquery und nicht als eigene Recording
Rule. So wird sie rückwirkend über die vorhandene Historie ausgewertet und ist
sofort wirksam, statt erst eine Stunde Vorlauf zu brauchen.

Nebenwirkung, die man kennen muss: Hängt ein Alarm dauerhaft, friert die Baseline
auf ihrem letzten gesunden Stand ein. Das ist gewollt – aber es heißt auch, dass
ein vergessener Dauer-Alarm das Nachlernen bei einer *legitimen* Änderung
blockiert.

### Warum die Erkennung Minuten braucht, nicht Sekunden

Sieben Minuten klingen lang, sind hier aber physikalisch begründet: Der
Checkout-Endpunkt bekommt nachts rund zwei Requests pro Minute. Bis ein
gleitendes 5-Minuten-Fenster überwiegend mit den langsamen Requests gefüllt ist,
vergehen etwa fünf Minuten, dazu kommen zwei Minuten `for`-Bestätigung. Aus zwei
Messwerten pro Minute lässt sich eine Verteilungsverschiebung nicht schneller
statistisch belegen – wer hier auf Sekunden verkürzt, kauft sich Fehlalarme ein.

Deshalb die Arbeitsteilung: `DependencyDegraded` arbeitet mit einem festen
Schwellwert und meldet den Verursacher schnell, die baseline-basierten Detektoren
bestätigen und ordnen ein. In der Vorführung ist der schnelle Alarm der, den man
zeigt; die anderen liefern die Begründung.

### Die roten Linien im Dashboard

Die senkrechten roten Striche sind **Annotationen vergangener Alarme**, keine
aktuellen. Sie zeichnen die Historie des gewählten Zeitfensters – bei sechs
Stunden Rückblick sammelt sich da einiges an, auch wenn gerade nichts brennt.
Sie sind jetzt auf `severity=critical` eingeschränkt und über den Schalter
„Kritische Alarme" links oben abschaltbar. Der Balken „Gesamtstatus" in der
Alarm-Historie ist grün, solange nichts feuert.

## KI-Integration

Zwei zusätzliche Bausteine, beide lokal (kein API-Key, kein Internetzugriff im
laufenden Betrieb – nur der einmalige Modell-Download braucht Netz):

### KI-Analyse-Chat (`services/ai-analyst`, Port 8090)

Ein Chat, in dem man in natürlicher Sprache fragen kann, z. B. „warum ist
checkout gerade langsam?". Verlinkt im Panel „Demo-Steuerung" beider
Dashboards.

**Architektur – bewusst kein reiner Agentic-Loop:** Das lokale Modell ist klein
(1,5 Mrd. Parameter, siehe unten warum), und kleine Modelle rufen Tools
unzuverlässig auf. Deshalb hängt die Grundqualität der Antwort nicht davon ab,
ob das Modell ein Tool korrekt aufruft:

1. Bei jeder Anfrage wird zuerst **deterministisch** (kein Modellaufruf) ein
   Kontext-Bündel zusammengestellt: aktive/pending Alarme aus vmalert, SLIs
   beider Anwendungen (Traffic, Fehlerrate, P95, saisonales Verhältnis,
   gelernte Vergleichstage), die fünf langsamsten Downstream-Systeme, aktives
   Chaos-Szenario. Dieses Bündel steht im Chat rechts sichtbar – Transparenz
   ist bei einem so kleinen Modell wichtig, damit man sieht, worauf die
   Antwort beruht.
2. Zusätzlich bietet der Chat drei Tools für Drill-down an (`query_promql`,
   `query_recent_logs`, `query_recent_traces` gegen VictoriaMetrics/Loki/Tempo),
   die das Modell optional aufrufen kann. Ruft es keins oder ein fehlerhaftes
   auf, bleibt die Antwort trotzdem brauchbar, weil das Kontext-Bündel schon
   im Prompt steht.

**Modellwahl:** `llama-3.3-70b-versatile` über die kostenlose
[Groq-API](https://console.groq.com/keys) (OpenAI-kompatibel, Endpunkt
`https://api.groq.com/openai/v1`). Vorher lief hier ein lokales 1,5B-Modell
per Ollama – Docker Desktop stellt in dieser Umgebung nur **~3,8 GB RAM**
insgesamt bereit, ein Modell dieser Größenklasse hätte dort nicht zuverlässig
Platz gehabt, und Tool-Calling war bei 1,5 Mrd. Parametern nicht verlässlich
(deshalb das deterministische Kontext-Bündel als Fundament, siehe oben). Groq
löst beide Probleme: kein lokaler RAM-Bedarf, und ein 70B-Modell ruft die
angebotenen Tools deutlich zuverlässiger auf.

- Ist `GROQ_API_KEY` nicht gesetzt oder Groq nicht erreichbar, liefert der
  Chat trotzdem den reinen Kontext-Bündel-Text zurück statt eines Fehlers
  (siehe `run_chat()` in [`services/ai-analyst/main.py`](services/ai-analyst/main.py)).
- Groqs kostenloses Kontingent hat ein Rate-Limit pro Minute/Tag; für eine
  Demo-Session reicht das komfortabel, für Dauerbetrieb lohnt ein Blick auf
  [console.groq.com](https://console.groq.com) für aktuelle Limits.

### KI direkt in Grafana (`grafana-llm-app`)

Zusätzlich ist das offizielle Grafana-Plugin `grafana-llm-app` installiert
(`GF_INSTALL_PLUGINS` in `docker-compose.yml`) und über
[`config/grafana-llm-provisioning.yaml`](config/grafana-llm-provisioning.yaml)
auf dieselbe Groq-API verdrahtet wie der eigene Chat – der API-Key kommt zur
Laufzeit per `GF_ENABLE_ENVIRONMENT_VARIABLE_EXPANSION` aus derselben
`GROQ_API_KEY`-Umgebungsvariable, steht also nirgends im Repo. Provider-Wahl
und Modellname müssen einmalig per UI nachgetragen werden (**Administration →
Plugins and data → Plugins → LLM → Configuration**), das lässt sich aus der
Provisioning-Datei allein nicht vollständig setzen.

Die vorher dokumentierte Timeout-Problematik der Plugin-„Ein-Klick"-Features
(z. B. „✨ Auto-generate") betraf das langsame CPU-only-Lokalmodell; mit
Groqs deutlich kürzeren Antwortzeiten ist sie in der Praxis nicht mehr
relevant, wurde hier aber nicht erneut nachgemessen.

### ML-gestützte Anomalie-Erkennung (`services/ml-anomaly`)

Ergänzt (ersetzt nicht) die handgebaute PromQL-Heuristik aus dem Abschnitt
oben um eine echte Zeitreihenzerlegung: **MSTL** (statsmodels) trennt Trend
von täglicher und – sobald genug Historie da ist – wöchentlicher
Saisonalität. Läuft alle 2 Minuten für sechs Reihen (Traffic, P95-Latenz,
Geschäftsvolumen × beide Anwendungen), schreibt Erwartungswert und ein
±3-Sigma-Band der Residuen zurück nach VictoriaMetrics
(`ml:<metrik>:forecast/upper/lower`).

Das 2-Minuten-Intervall ist kein Performance-Detail: VictoriaMetrics'
Instant-Queries haben ein Staleness-Fenster von 5 Minuten. Bei den ursprünglich
geplanten 15 Minuten wären die `ml:*`-Reihen für vmalert 10 von 15 Minuten
schlicht "nicht vorhanden" gewesen – die Alarme hätten nie zuverlässig
auswerten können. Die Dekomposition selbst dauert für alle sechs Reihen nur
1-2 Sekunden, ein kürzeres Intervall kostet also praktisch nichts.

**Kaltstart-Schwellen** (eigene, konservative Entscheidung dieses Dienstes –
statsmodels selbst macht dazu keine Vorgabe): unter 2 Tagen Historie gibt es
keine Vorhersage, ab 2 Tagen nur das Tagesmuster, ab 14 Tagen zusätzlich das
Wochenmuster. Dank der 8 Tage aus `scripts/seed-history.py` stand das
Tagesmuster in diesem PoC sofort zur Verfügung.

Neue Alarme `MLAnomalyDetected` / `MLTrafficAnomalyDetected` vergleichen Ist
gegen das Band. Neue Panel-Zeile „ML-gestützte Prognose" in beiden
Dashboards, inklusive Stat-Panel „ML-Modellreife" (0/1/2 Zyklen) – dasselbe
Transparenzprinzip wie bei `poc:learning:profile_days`.

Der Sinn dieser zweiten, unabhängigen Erkennung: in der Vorführung lässt sich
„einfache MetricsQL-Heuristik vs. echtes statistisches Modell" direkt
nebeneinander zeigen, statt nur zu behaupten, dass eines besser ist.

### Grenzen dieses PoC

- Die kurzfristige Anomalie-Erkennung ist ein Z-Score über ein 15-Minuten-Fenster,
  kein trainiertes Modell. Das saisonale Tagesprofil (vier Vergleichstage,
  Ausschluss von Alarm-Zeiträumen) mildert das für Tages-/Wochenmuster ab, ist
  aber selbst nur ein gleitender Mittelwert über Lag-Fenster. `services/ml-anomaly`
  (siehe oben) ist der Schritt zu echtem ML (MSTL-Zerlegung), erkennt damit
  Tages-/Wochenmuster robuster – aber auch das ist noch kein Modell, das
  Feiertage, Sonderaktionen oder einen echten Trend gesondert behandelt. Dafür
  bräuchte es in Produktion externe Kalenderdaten oder ein trainiertes,
  regelmäßig nachjustiertes Modell.
- Das lokale LLM (`qwen2.5:1.5b`) ist klein, weil nur ~3,8 GB Docker-RAM zur
  Verfügung standen. CPU-only-Inferenz ohne GPU ist entsprechend langsam
  (~20 s pro Antwort, selbst mit hartem Token-Limit) und Tool-Calling ist bei
  dieser Größe nicht durchgehend verlässlich. Für produktiven Einsatz mit
  echten Antwortzeiten bräuchte es entweder mehr RAM/GPU-Zugriff für ein
  größeres lokales Modell oder eine Cloud-API.
- Hält eine Störung länger als etwa fünf Minuten an, wächst die kurzfristige
  Baseline langsam mit und der Z-Score sinkt. Für Dauerzustände sind
  `HighErrorRate` und `DependencyDegraded` zuständig.
- Nach dem Start braucht die kurzfristige Baseline rund 15 Minuten Historie,
  das saisonale Profil bis zu einer Woche – deshalb der einmalige Seed über
  `scripts/seed-history.py`. Vorher greifen jeweils Fallback-Ketten.
- Die Microservices hinter den beiden Einstiegspunkten sind simuliert, nicht
  real deployt. Telemetrie, Topologie und Trace-Struktur sind aber echt.
- VictoriaMetrics hat jetzt ein benanntes Volume und 30 Tage Aufbewahrung –
  Voraussetzung fürs saisonale Lernen. Grafana und Tempo haben weiterhin keine
  Volumes; ihre Daten (Dashboards kommen aus dem Bind-Mount, Traces sind ohnehin
  kurzlebig) sind nach einem Neustart weg, das betrifft aber nicht das Lernen.

## Betrieb

Configs liegen als Bind-Mount im Container. Docker Compose erkennt Änderungen an
gemounteten Dateien nicht, deshalb nach jeder Config-Änderung:

```bash
docker compose up -d --force-recreate grafana tempo vmalert
```

Ein `docker compose restart` reicht **nicht** – Grafana zieht die Data Sources
dann nicht neu.

Dashboard-Änderungen in [`dashboards/`](dashboards/) werden dagegen alle
10 Sekunden automatisch übernommen.
