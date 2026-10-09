<img src="custom_components/alamos/brand/icon.png" alt="Alamos" width="96" align="right">

# Alamos für Home Assistant (aPager PRO / AMweb)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/sebiweise/home-assistant-alamos/actions/workflows/validate.yml/badge.svg)](https://github.com/sebiweise/home-assistant-alamos/actions/workflows/validate.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=sebiweise_home-assistant-alamos&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=sebiweise_home-assistant-alamos)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=sebiweise_home-assistant-alamos&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=sebiweise_home-assistant-alamos)
[![GitHub Release](https://img.shields.io/github/v/release/sebiweise/home-assistant-alamos)](https://github.com/sebiweise/home-assistant-alamos/releases)

Eine Home-Assistant-Integration für die Alarmierungslösungen der [Alamos GmbH](https://www.alamos.gmbh)
(aPager PRO, AMweb, FE2). Sie bringt drei Funktionen mit:

1. **Webhook-Empfang**: aPager PRO („Allgemeine Webhooks“) und AMweb („Webhooks“) melden Alarme an Home Assistant.
   Daraus werden ein Alarm-Binärsensor, Sensoren für Stichwort und Einheit, eine Event-Entität und Events auf dem Bus.
2. **Alamos API (Verfügbarkeit / Alarmrückmeldung)**: Über die [Alamos API](https://alamos-support.atlassian.net/wiki/spaces/documentation/pages/2472509441/API)
   kannst du dich per Button, Service oder Automation auf alle Alarme der letzten 3 Minuten zurückmelden (Zusage/Absage).
3. **FE2 – Externe Schnittstelle** *(optional)*: Home Assistant löst über einen eigenen FE2-Server Alarme aus,
   schließt sie wieder und meldet Fahrzeugstatus, z. B. bei einem Rauchmelder im Gerätehaus.

> [!WARNING]
> Diese Integration ist ein Community-Projekt und steht in keiner Verbindung zur Alamos GmbH.
> Das Alamos-Logo wird mit freundlicher Genehmigung der Alamos GmbH verwendet.
> Sie ersetzt keine zertifizierte Alarmierung. Verlasse dich im Einsatzfall nicht allein auf Home Assistant.

## Installation

### Über HACS (empfohlen)

1. HACS öffnen → Menü (⋮) → **Benutzerdefinierte Repositories**
2. URL `https://github.com/sebiweise/home-assistant-alamos` mit Kategorie **Integration** hinzufügen
3. „Alamos (aPager PRO / AMweb)“ installieren und Home Assistant neu starten
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Alamos**

### Manuell

Den Ordner `custom_components/alamos` nach `<config>/custom_components/alamos` kopieren und Home Assistant neu starten.

Das Logo liegt in `custom_components/alamos/brand/` und wird ab Home Assistant 2026.3 angezeigt.

## Einrichtung

Bei der Einrichtung werden abgefragt:

| Feld | Beschreibung |
| --- | --- |
| Name | Name des Geräts in Home Assistant, z. B. „Feuerwehr Musterhausen“ |
| API-Schlüssel | *Optional.* Nur für die Alarmrückmeldung nötig (siehe unten) |
| Bestätigungs-Push unterdrücken | Sendet `suppressNotification=true` an die API |
| Alarm automatisch zurücksetzen | Nach wie vielen Minuten der Alarm-Sensor wieder auf „aus“ geht (0 = nie) |

### Optionen

Unter **Einstellungen → Geräte & Dienste → Alamos → Konfigurieren** lassen sich zusätzlich einstellen:

| Option | Beschreibung |
| --- | --- |
| API-Schlüssel | Schlüssel ändern oder leeren (deaktiviert Buttons und Rückmelde-Service) |
| Bestätigungs-Push unterdrücken | Standardwert für `suppress_notification` |
| Alarm automatisch zurücksetzen | Minuten bis zum automatischen Zurücksetzen (0 = nie, z. B. bei AMweb mit „kein Alarm mehr offen“-URL) |
| Einheiten-Filter | Nur Alarme dieser Einheiten verarbeiten, z. B. `LZ1`, `Florian Musterhausen 1/44` (Groß-/Kleinschreibung egal). Alarme ohne übermittelte Einheit werden immer verarbeitet, damit kein echter Alarm verloren geht |
| Stichwörter für Probealarme | Enthält das Stichwort einen dieser Begriffe (z. B. `Probealarm`, `Test`), wird nur das Ereignis `test_alarm` ausgelöst. Alarm-Sensor und Zähler bleiben unverändert |
| Parametername Stichwort / Einheit | Falls in der aPager-PRO-App umbenannt (Standard `keyword` / `unit`) |
| API-Basis-URL | Nur ändern, falls Alamos den Server wechselt |
| FE2-URL | *Optional.* Adresse der FE2-Weboberfläche, z. B. `http://192.168.1.10:83`. Aktiviert die FE2-Aktionen (siehe [FE2 – Externe Schnittstelle](#fe2--externe-schnittstelle)) |
| FE2-Absender | Wird in FE2 als Quelle gespeichert (Standard `Home Assistant`) |
| FE2-Autorisierung | Shared Secret, das im FE2-Alarmeingang unter „Gültige Absender“ eingetragen ist |

Nach dem Abschluss zeigt Home Assistant die **Webhook-URLs** an. Du findest sie später jederzeit in den
**Optionen** der Integration. Sie haben folgende Form:

```
https://<deine-ha-url>/api/webhook/<webhook_id>               # neuer Alarm
https://<deine-ha-url>/api/webhook/<webhook_id>?event=recall  # Rückalarm / Alarmabbruch
https://<deine-ha-url>/api/webhook/<webhook_id>?event=clear   # kein Alarm mehr offen
```

Bei POST darf `event` auch im JSON-Body stehen.

| `event` | Wirkung |
| --- | --- |
| `recall` (oder `cancel`) | **Rückalarm**: beendet den Alarm und löst `alamos_alarm_cleared` mit `recall: true`, `keyword`, `unit` und `data` aus, auch wenn gerade kein Alarm aktiv ist. Ein Rückalarm einer anderen Einheit wird bei gesetztem Einheiten-Filter ignoriert |
| `clear` (oder `reset`, `end`, `idle`, `off`) | Beendet den Alarm; das Event kommt nur, wenn ein Alarm aktiv war |

> [!IMPORTANT]
> Die URL muss von außen per **HTTPS** erreichbar sein, etwa über Home Assistant Cloud (Nabu Casa) oder einen Reverse Proxy.
> iOS blockiert `http://`-URLs. Behandle die Webhook-ID wie ein Passwort.

### aPager PRO – Allgemeine Webhooks

In der App unter **Einstellungen → Smart Home → Webhooks** (Smart-Home-Abo erforderlich):

- **URL**: die Webhook-URL von oben
- **Methode**: `GET` oder `POST`. Beides wird unterstützt; POST sendet ein JSON-Objekt.
- **Einheit / Stichwort übertragen** aktivieren. Die Standard-Parameternamen `unit` und `keyword` passen ohne Änderung.
  Wenn du sie in der App umbenennst, trage die neuen Namen in den Optionen der Integration ein.

Der aPager PRO löst Webhooks nur bei echten Alarmen aus (Reiter „Alarm“), nicht bei Info-, Unwetter- oder Statusalarmen.

Für Rückalarme/Alarmabbrüche legst du einen **zweiten Webhook** mit der URL `…?event=recall` an und lässt ihn nur bei
einem Rückalarm auslösen. Ob und wie die App einen Webhook auf Rückalarme beschränken kann, hängt von deiner
aPager-PRO-Version und Konfiguration ab (nicht anhand der Alamos-Doku geprüft).

### AMweb – Webhooks

AMweb ruft die hinterlegten URLs per `GET` auf:

- **Neuer Alarm** → `https://<deine-ha-url>/api/webhook/<webhook_id>`
- **Kein Alarm mehr offen** → `https://<deine-ha-url>/api/webhook/<webhook_id>?event=clear`

### Alamos API – Alarmrückmeldung

1. In der aPager PRO App → **Verfügbarkeit** → ganz unten **Externer Zugriff** → API-Schlüssel erzeugen.
   Der Schlüssel gilt nur für das Profil (die Organisation), in dem er erzeugt wurde.
2. Den Schlüssel bei der Einrichtung oder später in den Optionen eintragen.
3. Ein aktives **Smart-Home-Abo** ist Voraussetzung.

Die Integration ruft folgenden Endpunkt auf:

```
GET https://alamos-backend.ey.r.appspot.com/fe2/feedback/user/external
    ?authToken=<API-Schlüssel>&mode=accept|reject[&suppressNotification=true]
```

| HTTP-Status | Bedeutung | Sensor „Letzte Rückmeldung“ |
| --- | --- | --- |
| 200 | Rückmeldung für mindestens einen Alarm gespeichert | `success` |
| 204 | Kein Alarm in den letzten 3 Minuten | `no_alarm` |
| 403 | API-Schlüssel falsch | `invalid_api_key` |
| 409 | Smart-Home-Abo oder Lizenz fehlt | `no_subscription` |

Falls Alamos die Basis-URL ändert, kannst du sie in den Optionen anpassen.

### FE2 – Externe Schnittstelle

Betreibst du einen eigenen **Alamos FE2**-Server, kann Home Assistant über dessen Alarmeingang
„Externe Schnittstelle“ Alarme auslösen, aktualisieren und schließen sowie Fahrzeugstatus melden,
z. B. wenn ein Rauch- oder Wassermelder im Gerätehaus auslöst.

1. In FE2 einen Alarmeingang **Externe Schnittstelle** anlegen und **HTTP POST** aktivieren.
2. Unter **Gültige Absender** ein Shared Secret eintragen (z. B. eine lange Zufallszeichenfolge).
3. Optional **Standard-Einheiten** festlegen; sie werden alarmiert, wenn die Aktion keine Einheiten übergibt.
4. In den Optionen der Integration **FE2-URL** (Port der FE2-Weboberfläche, Standard `83`) und
   **FE2-Autorisierung** (das Shared Secret) eintragen.

Die Integration sendet UTF-8-JSON im Datenformat v2 an:

```
POST <FE2-URL>/rest/external/http/alarm/v2    # Alarm (type ALARM) und Alarm schließen (type CLOSE)
POST <FE2-URL>/rest/external/http/status/v2   # Fahrzeugstatus (type STATUS)
```

| HTTP-Status | Bedeutung |
| --- | --- |
| 200 + `{"status": "OK"}` | Erfolgreich übergeben |
| 200 + `{"status": "NOT_OK"}` / 400 | Aufruf fehlerhaft, Details im Feld `error` |
| 406 | Der Alarmeingang ist deaktiviert |
| 409 | Konflikt mit Einstellungen/Voraussetzungen in FE2 |

Fehler werden als Fehlermeldung der Aktion angezeigt. Grundlage ist die Alamos-Doku zur externen Schnittstelle
(„Zugriff via HTTP POST/GET“, „Datenformat Externe Schnittstelle“); mit einem echten FE2-System ist das noch nicht getestet.

## Entitäten

| Entität | Beschreibung |
| --- | --- |
| `binary_sensor.<name>_alarm` | `on`, solange ein Alarm aktiv ist. Attribute: `keyword`, `unit`, `source`, `data` (alle empfangenen Parameter), `feedback_deadline` (bis wann eine Rückmeldung über die API möglich ist) |
| `event.<name>_alarm_event` | Event-Entität mit den Event-Typen `alarm`, `test_alarm` und `cleared` (bei `event=recall` mit `recall: true`, `keyword`, `unit`, `data`) |
| `sensor.<name>_keyword` | Stichwort des letzten Alarms |
| `sensor.<name>_unit` | Einheit des letzten Alarms |
| `sensor.<name>_last_alarm` | Zeitpunkt des letzten Alarms |
| `sensor.<name>_alarm_count` | Anzahl empfangener Alarme (Diagnose) |
| `sensor.<name>_last_feedback` | Ergebnis der letzten API-Rückmeldung *(nur mit API-Schlüssel)* |
| `button.<name>_accept_alarm` | Alarm zusagen *(nur mit API-Schlüssel)* |
| `button.<name>_reject_alarm` | Alarm absagen *(nur mit API-Schlüssel)* |

## Services

### `alamos.send_feedback`

```yaml
action: alamos.send_feedback
data:
  mode: accept            # accept | reject
  suppress_notification: true   # optional
  config_entry_id: abc123 # optional, sonst alle Einträge mit API-Schlüssel
response_variable: result # optional: {"results": [{"status": 200, "result": "success", ...}]}
```

### `alamos.reset_alarm`

Setzt den Alarm-Sensor zurück (optional `config_entry_id`).

### `alamos.fe2_send_alarm`

Erstellt einen Alarm in FE2 oder aktualisiert ihn (gleiche `external_id`). `keyword` oder `message` ist Pflicht,
alle anderen Felder sind optional.

```yaml
action: alamos.fe2_send_alarm
data:
  keyword: BMA
  keyword_description: Brandmeldeanlage
  message: "Rauchmelder Gerätehaus Keller"   # mehrere Zeilen = mehrere Einträge
  units: ["1234567"]       # leer = Standard-Einheiten des Alarmeingangs
  external_id: ha-bma-1    # optional, sonst wird eine ID erzeugt
  street: Musterstraße
  house: "10"
  postal_code: "12345"
  city: Musterhausen
  building: Gerätehaus
  latitude: 50.12345
  longitude: 10.123456
  caller_name: Home Assistant
  caller_contact: "0123 456789"
  custom:                  # beliebige Zusatzdaten (data.custom)
    remark: Ausgelöst durch binary_sensor.rauchmelder_keller
response_variable: fe2     # {"results": [{"status": 200, "external_id": "ha-bma-1", ...}]}
```

### `alamos.fe2_close_alarm`

Schließt einen Alarm anhand seiner externen ID.

```yaml
action: alamos.fe2_close_alarm
data:
  external_id: "{{ fe2.results[0].external_id }}"
```

### `alamos.fe2_send_status`

Meldet einen Fahrzeugstatus. `address` (Fahrzeugkennung) oder `radio_name` ist Pflicht.

```yaml
action: alamos.fe2_send_status
data:
  status: "2"
  event: Wache an
  radio_name: LF 40/1
  latitude: 48.342424     # optional, zusammen mit longitude
  longitude: 10.905622
```

Alle FE2-Aktionen akzeptieren `config_entry_id`; ohne Angabe gehen sie an alle Einträge mit FE2-URL.

## Events

| Event | Daten |
| --- | --- |
| `alamos_alarm` | `config_entry_id`, `name`, `keyword`, `unit`, `data`, `test` (`true` bei Probealarm), `feedback_deadline` (ISO-Zeitstempel, Alarm + 3 Minuten) |
| `alamos_alarm_cleared` | `config_entry_id`, `name`; bei `event=recall` zusätzlich `recall: true`, `keyword`, `unit`, `data` |

## Blueprints

Fertige Automationen zum Importieren. Sie liegen in [`blueprints/automation/alamos`](blueprints/automation/alamos)
und werden in der CI automatisch mit Home Assistant getestet.

### Rückmeldung per Benachrichtigung

[![Blueprint importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsebiweise%2Fhome-assistant-alamos%2Fblob%2Fmaster%2Fblueprints%2Fautomation%2Falamos%2Factionable_notification.yaml)

Schickt bei jedem Alarm eine Benachrichtigung mit den Buttons **„✅ Komme“** und **„❌ Komme nicht“** an die
Home Assistant Companion App. Ein Tipp auf einen Button meldet über die Alamos-API zurück; anschließend
zeigt die Benachrichtigung das Ergebnis an (übermittelt / kein Alarm gefunden / Fehler).

- Optional als **kritische Benachrichtigung**, die „Nicht stören“ durchbricht (iOS: kritische Mitteilung,
  Android: Kanal `alarm_stream`)
- Läuft automatisch ab, sobald die 3-Minuten-Frist der Alamos-API vorbei ist
- Probealarme werden standardmäßig ignoriert
- Unterdrückt auf Wunsch die doppelte Bestätigung der aPager-PRO-App

> [!NOTE]
> Benötigt einen API-Schlüssel mit aktivem Smart-Home-Abo. Für kritische Mitteilungen auf iOS muss die
> Companion App unter *Einstellungen → Mitteilungen* kritische Mitteilungen erlauben.

### Licht bei Alarm

[![Blueprint importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsebiweise%2Fhome-assistant-alamos%2Fblob%2Fmaster%2Fblueprints%2Fautomation%2Falamos%2Falarm_lights.yaml)

Schaltet gewählte Lichter (z. B. Flur, Treppe, Einfahrt) mit einstellbarer Helligkeit ein, optional nur bei
Dunkelheit. Nach Alarmende oder spätestens nach der eingestellten Zeit wird der vorherige Zustand wiederhergestellt.

### Automatische Rückmeldung nach Anwesenheit

[![Blueprint importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsebiweise%2Fhome-assistant-alamos%2Fblob%2Fmaster%2Fblueprints%2Fautomation%2Falamos%2Fpresence_feedback.yaml)

Meldet abhängig davon zurück, ob eine Person in einer Zone ist, z. B. „zu Hause → Zusage“ oder
„Urlaub/außerhalb → Absage“. Jeder Fall kann auch auf „Nichts tun“ stehen.

## Weitere Beispiel-Automationen

**Stichwort per Sprachausgabe ansagen**

```yaml
automation:
  - alias: "Alarm: Durchsage"
    triggers:
      - trigger: event
        event_type: alamos_alarm
        event_data:
          test: false
    actions:
      - action: tts.speak
        target:
          entity_id: tts.home_assistant_cloud
        data:
          media_player_entity_id: media_player.kueche
          message: >-
            Alarm für {{ trigger.event.data.unit or 'die Feuerwehr' }}:
            {{ trigger.event.data.keyword }}
```

**Bei Rückalarm benachrichtigen**

```yaml
automation:
  - alias: "Rückalarm: Benachrichtigung"
    triggers:
      - trigger: event
        event_type: alamos_alarm_cleared
        event_data:
          recall: true
    actions:
      - action: notify.mobile_app_mein_handy
        data:
          title: "Rückalarm"
          message: >-
            Einsatz abgebrochen{{ ': ' ~ trigger.event.data.keyword
            if trigger.event.data.keyword else '' }}
```

**Musik und Fernseher pausieren**

```yaml
automation:
  - alias: "Alarm: Medien pausieren"
    triggers:
      - trigger: state
        entity_id: binary_sensor.feuerwehr_alarm
        to: "on"
    actions:
      - action: media_player.media_pause
        target:
          entity_id:
            - media_player.wohnzimmer
            - media_player.fernseher
```

**Probealarm nur still melden**

```yaml
automation:
  - alias: "Probealarm protokollieren"
    triggers:
      - trigger: state
        entity_id: event.feuerwehr_alarm_event
    conditions:
      - condition: state
        entity_id: event.feuerwehr_alarm_event
        attribute: event_type
        state: test_alarm
    actions:
      - action: persistent_notification.create
        data:
          title: Probealarm empfangen
          message: "{{ state_attr('event.feuerwehr_alarm_event', 'keyword') }}"
```

**Bei Alarm nachts Rolllade im Schlafzimmer öffnen und Kaffeemaschine starten**

```yaml
automation:
  - alias: "Alarm: nachts aufstehen"
    triggers:
      - trigger: state
        entity_id: binary_sensor.feuerwehr_alarm
        to: "on"
    conditions:
      - condition: time
        after: "22:00:00"
        before: "06:00:00"
    actions:
      - action: cover.open_cover
        target:
          entity_id: cover.schlafzimmer
      - action: switch.turn_on
        target:
          entity_id: switch.kaffeemaschine
```

**Garagentor öffnen, wenn ich zugesagt habe**

```yaml
automation:
  - alias: "Alarm: Garage nach Zusage öffnen"
    triggers:
      - trigger: state
        entity_id: sensor.feuerwehr_last_feedback
        to: success
    conditions:
      - condition: template
        value_template: "{{ state_attr('sensor.feuerwehr_last_feedback', 'mode') == 'accept' }}"
      - condition: state
        entity_id: binary_sensor.feuerwehr_alarm
        state: "on"
    actions:
      - action: cover.open_cover
        target:
          entity_id: cover.garage
```

**Alarm am Dashboard anzeigen** (Markdown-Karte, nur sichtbar während eines Alarms)

```yaml
type: markdown
visibility:
  - condition: state
    entity: binary_sensor.feuerwehr_alarm
    state: "on"
content: >-
  ## 🚨 {{ state_attr('binary_sensor.feuerwehr_alarm', 'keyword') }}

  **Einheit:** {{ state_attr('binary_sensor.feuerwehr_alarm', 'unit') or '–' }}

  **Alarmiert:** {{ states('sensor.feuerwehr_last_alarm') | as_timestamp | timestamp_custom('%H:%M') }} Uhr
```

## Entwicklung

### Devcontainer (empfohlen)

Das Repository enthält einen [Devcontainer](.devcontainer/devcontainer.json) für VS Code / GitHub Codespaces
(Python 3.14, Ruff, Pytest). Nach dem Öffnen werden die Abhängigkeiten automatisch installiert.

| Befehl | Zweck |
| --- | --- |
| `scripts/develop` | Startet eine lokale Home-Assistant-Instanz mit der Integration auf Port 8123 (Konfiguration in `config/`) |
| `scripts/test` | Ruff (Lint + Format) und Pytest, wie in der CI |
| `scripts/setup` | Installiert die gesperrten Abhängigkeiten aus `requirements_test.txt` |
| `scripts/lock` | Erzeugt `requirements_test.txt` (mit Hashes) neu aus `requirements_test.in` |

### Ohne Devcontainer

Benötigt Python 3.14 (aktuelle Home-Assistant-Versionen setzen ≥ 3.14.2 voraus).

```bash
scripts/setup
scripts/test
```

### Abhängigkeiten

Die Test-Abhängigkeiten sind in `requirements_test.txt` inklusive Hashes gesperrt und werden ausschließlich
als Wheels installiert (`--only-binary :all: --require-hashes`). Ausnahmen sind nur `mock-open` und `pyric`,
die ausschließlich als Quellpaket veröffentlicht werden. Dependabot aktualisiert sie wöchentlich,
ebenso die per Commit-SHA gepinnten GitHub Actions und das Devcontainer-Image.

## Lizenz

[MIT](LICENSE)
