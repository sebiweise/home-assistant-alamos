# Alamos für Home Assistant (aPager PRO / AMweb)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/sebiweise/home-assistant-alarmos/actions/workflows/validate.yml/badge.svg)](https://github.com/sebiweise/home-assistant-alarmos/actions/workflows/validate.yml)

Eine Home-Assistant-Integration für die Alarmierungslösungen der [Alamos GmbH](https://www.alamos.gmbh)
(aPager PRO, AMweb). Sie bringt zwei Funktionen mit:

1. **Webhook-Empfang**: aPager PRO („Allgemeine Webhooks“) und AMweb („Webhooks“) melden Alarme an Home Assistant.
   Daraus werden ein Alarm-Binärsensor, Sensoren für Stichwort und Einheit, eine Event-Entität und Events auf dem Bus.
2. **Alamos API (Verfügbarkeit / Alarmrückmeldung)**: Über die [Alamos API](https://alamos-support.atlassian.net/wiki/spaces/documentation/pages/2472509441/API)
   kannst du dich per Button, Service oder Automation auf alle Alarme der letzten 3 Minuten zurückmelden (Zusage/Absage).

> [!WARNING]
> Diese Integration ist ein Community-Projekt und steht in keiner Verbindung zur Alamos GmbH.
> Sie ersetzt keine zertifizierte Alarmierung. Verlasse dich im Einsatzfall nicht allein auf Home Assistant.

## Installation

### Über HACS (empfohlen)

1. HACS öffnen → Menü (⋮) → **Benutzerdefinierte Repositories**
2. URL `https://github.com/sebiweise/home-assistant-alarmos` mit Kategorie **Integration** hinzufügen
3. „Alamos (aPager PRO / AMweb)“ installieren und Home Assistant neu starten
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Alamos**

### Manuell

Den Ordner `custom_components/alamos` nach `<config>/custom_components/alamos` kopieren und Home Assistant neu starten.

## Einrichtung

Bei der Einrichtung werden abgefragt:

| Feld | Beschreibung |
| --- | --- |
| Name | Name des Geräts in Home Assistant, z. B. „Feuerwehr Musterhausen“ |
| API-Schlüssel | *Optional.* Nur für die Alarmrückmeldung nötig (siehe unten) |
| Bestätigungs-Push unterdrücken | Sendet `suppressNotification=true` an die API |
| Alarm automatisch zurücksetzen | Nach wie vielen Minuten der Alarm-Sensor wieder auf „aus“ geht (0 = nie) |

Nach dem Abschluss zeigt Home Assistant die **Webhook-URLs** an. Du findest sie später jederzeit in den
**Optionen** der Integration. Sie haben folgende Form:

```
https://<deine-ha-url>/api/webhook/<webhook_id>              # neuer Alarm
https://<deine-ha-url>/api/webhook/<webhook_id>?event=clear  # kein Alarm mehr offen
```

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

### AMweb – Webhooks

AMweb ruft die hinterlegten URLs per `GET` auf:

- **Neuer Alarm** → `https://<deine-ha-url>/api/webhook/<webhook_id>`
- **Kein Alarm mehr offen** → `https://<deine-ha-url>/api/webhook/<webhook_id>?event=clear`

Statt `event=clear` werden auch `reset`, `end`, `idle` und `off` akzeptiert.

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

## Entitäten

| Entität | Beschreibung |
| --- | --- |
| `binary_sensor.<name>_alarm` | `on`, solange ein Alarm aktiv ist. Attribute: `keyword`, `unit`, `source`, `data` (alle empfangenen Parameter) |
| `event.<name>_alarm_event` | Event-Entität mit den Event-Typen `alarm` und `cleared` |
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

## Events

| Event | Daten |
| --- | --- |
| `alamos_alarm` | `config_entry_id`, `name`, `keyword`, `unit`, `data` |
| `alamos_alarm_cleared` | `config_entry_id`, `name` |

## Beispiel-Automationen

**Licht bei Alarm einschalten und Stichwort ansagen**

```yaml
automation:
  - alias: "Alarm: Flurlicht an"
    triggers:
      - trigger: state
        entity_id: binary_sensor.feuerwehr_alarm
        to: "on"
    actions:
      - action: light.turn_on
        target:
          entity_id: light.flur
        data:
          brightness_pct: 100
      - action: tts.speak
        target:
          entity_id: tts.home_assistant_cloud
        data:
          media_player_entity_id: media_player.kueche
          message: "Alarm: {{ state_attr('binary_sensor.feuerwehr_alarm', 'keyword') }}"
```

**Automatisch zusagen, wenn ich zu Hause bin**

```yaml
automation:
  - alias: "Alarm: automatisch zusagen"
    triggers:
      - trigger: event
        event_type: alamos_alarm
    conditions:
      - condition: state
        entity_id: person.ich
        state: home
    actions:
      - delay: "00:00:05"
      - action: alamos.send_feedback
        data:
          mode: accept
```

## Entwicklung

```bash
pip install -r requirements_test.txt ruff
pytest
ruff check custom_components tests && ruff format --check custom_components tests
```

## Veröffentlichung in HACS

Als *Custom Repository* lässt sich die Integration sofort nutzen. Für die Aufnahme in den HACS-Standardkatalog
(siehe [HACS – Publish](https://www.hacs.xyz/docs/publish/start/)):

1. Repository öffentlich machen, Beschreibung und Topics (z. B. `home-assistant`, `hacs`, `alamos`) setzen
2. Icon/Logo im Repository [home-assistant/brands](https://github.com/home-assistant/brands) für die Domain `alamos` einreichen
   und danach `ignore: brands` aus `.github/workflows/validate.yml` entfernen
3. Ein GitHub-Release erstellen (z. B. `v0.1.0`, passend zu `version` in `manifest.json`)
4. PR an [hacs/default](https://github.com/hacs/default) stellen
