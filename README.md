<img src="custom_components/alamos/brand/icon.png" alt="Alamos" width="96" align="right">

# Alamos für Home Assistant (aPager PRO / AMweb)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/sebiweise/home-assistant-alamos/actions/workflows/validate.yml/badge.svg)](https://github.com/sebiweise/home-assistant-alamos/actions/workflows/validate.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=sebiweise_home-assistant-alamos&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=sebiweise_home-assistant-alamos)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=sebiweise_home-assistant-alamos&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=sebiweise_home-assistant-alamos)
[![GitHub Release](https://img.shields.io/github/v/release/sebiweise/home-assistant-alamos)](https://github.com/sebiweise/home-assistant-alamos/releases)

Eine Home-Assistant-Integration für die Alarmierungslösungen der [Alamos GmbH](https://www.alamos.gmbh)
(aPager PRO, AMweb). Sie bringt zwei Funktionen mit:

1. **Webhook-Empfang**: aPager PRO („Allgemeine Webhooks“) und AMweb („Webhooks“) melden Alarme an Home Assistant.
   Daraus werden ein Alarm-Binärsensor, Sensoren für Stichwort und Einheit, eine Event-Entität und Events auf dem Bus.
2. **Alamos API (Verfügbarkeit / Alarmrückmeldung)**: Über die [Alamos API](https://alamos-support.atlassian.net/wiki/spaces/documentation/pages/2472509441/API)
   kannst du dich per Button, Service oder Automation auf alle Alarme der letzten 3 Minuten zurückmelden (Zusage/Absage).

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
| Anzahl Webhooks | Für wie viele Webhooks (1 bis 5) es einen eigenen Alarmzähler gibt. Alle 5 Webhook-URLs sind immer aktiv (siehe [Mehrere Webhooks](#mehrere-webhooks)) |
| Einheiten-Filter | Nur Alarme dieser Einheiten verarbeiten, z. B. `LZ1`, `Florian Musterhausen 1/44` (Groß-/Kleinschreibung egal). Alarme ohne übermittelte Einheit werden immer verarbeitet, damit kein echter Alarm verloren geht |
| Favoriten-Einheit | Werden mehrere Einheiten alarmiert, steht diese Einheit immer an erster Stelle (Sensor „Einheit“, Attribute `unit` und `units`), egal in welcher Reihenfolge die Webhooks ankommen. Groß-/Kleinschreibung egal |
| Stichwörter für Probealarme | Enthält das Stichwort einen dieser Begriffe (z. B. `Probealarm`, `Test`), wird nur das Ereignis `test_alarm` ausgelöst. Alarm-Sensor und Zähler bleiben unverändert |
| Parametername Stichwort / Einheit | Falls in der aPager-PRO-App umbenannt (Standard `keyword` / `unit`) |
| Rohdaten im Verlauf speichern | Standardmäßig aus. Das Attribut `data` (alle empfangenen Parameter, unter Umständen mit Einsatzadresse oder Personendaten) steht dann nur im aktuellen Zustand, z. B. für Templates und Automationen, und wird nicht im Verlauf (Recorder) gespeichert. Einschalten, um es wie in früheren Versionen auch im Verlauf zu behalten |
| API-Basis-URL | Nur ändern, falls Alamos den Server wechselt |

Nach dem Abschluss zeigt Home Assistant die **Webhook-URLs** an. Du findest sie später jederzeit in den
**Optionen** der Integration. Sie haben folgende Form:

```
https://<deine-ha-url>/api/webhook/<webhook_id>               # neuer Alarm
https://<deine-ha-url>/api/webhook/<webhook_id>?event=recall  # Rückalarm / Alarmabbruch
https://<deine-ha-url>/api/webhook/<webhook_id>?event=clear   # kein Alarm mehr offen
```

Bei POST darf `event` auch im JSON-Body stehen.

### Mehrere Webhooks

Der aPager PRO kann bis zu 5 allgemeine Webhooks auslösen, z. B. einen je Einheit oder Organisation. Jeder Eintrag
hat dafür 5 Webhook-URLs, die immer aktiv sind; die Optionen zeigen alle an. `?event=recall` und `?event=clear`
funktionieren mit jeder davon.

Alle Webhooks teilen sich den Alarm-Sensor und die Einstellungen. Mit **Anzahl Webhooks** in den Optionen legst du fest,
für wie viele Webhooks es eigene Entitäten gibt (ab 2): einen Zähler `sensor.<name>_alarm_count_webhook_<n>` und eine
Event-Entität `event.<name>_alarm_event_webhook_<n>`. Ein Webhook zählt jeden Alarm einmal, auch wenn er in einen
laufenden Alarm zusammengefasst wird. `sensor.<name>_alarm_count` zählt weiterhin jeden Alarm genau einmal, egal über
wie viele Webhooks er kam. Verringerst du die Anzahl, werden die Entitäten der weggefallenen Webhooks entfernt; ihre URLs
nehmen aber weiter Alarme an.

Die Event-Entität eines Webhooks löst aus, sobald dieser Webhook einen Alarm meldet, auch wenn er in einen laufenden
Alarm zusammengefasst wird. `event.<name>_alarm_event` und das Event `alamos_alarm` kommen dagegen nur einmal je Alarm
und nennen nur den zuerst eingetroffenen Webhook. Für eine Automation, die auf einen bestimmten Webhook reagieren soll,
nimmst du daher dessen Event-Entität:

```yaml
triggers:
  - trigger: state
    entity_id: event.feuerwehr_alarm_event_webhook_2
conditions:
  - condition: state
    entity_id: event.feuerwehr_alarm_event_webhook_2
    attribute: event_type
    state: alarm
```

Probealarme (`test_alarm`) und Rückalarme (`cleared`) über diesen Webhook kommen dort ebenfalls an, je Webhook nur
einmal. Endet ein Alarm, egal wie (Rückalarm oder `?event=clear` über einen beliebigen Webhook, automatisches
Zurücksetzen, `alamos.reset_alarm`), bekommen alle Webhooks, die den Alarm gemeldet haben, `cleared`.

| `event` | Wirkung |
| --- | --- |
| `recall` (oder `cancel`) | **Rückalarm**: beendet den Alarm und löst `alamos_alarm_cleared` mit `recall: true`, `keyword`, `unit` und `data` aus, auch wenn gerade kein Alarm aktiv ist. Ein Rückalarm einer anderen Einheit wird bei gesetztem Einheiten-Filter ignoriert |
| `clear` (oder `reset`, `end`, `idle`, `off`) | Beendet den Alarm; das Event kommt nur, wenn ein Alarm aktiv war |

> [!IMPORTANT]
> Die URL muss von außen per **HTTPS** erreichbar sein, etwa über Home Assistant Cloud (Nabu Casa) oder einen Reverse Proxy.
> iOS blockiert `http://`-URLs. Behandle die Webhook-ID wie ein Passwort.

### aPager PRO – Allgemeine Webhooks

In der App unter **Einstellungen → Smart Home → Webhooks** (iOS) bzw. **Einstellungen → Labor** (Android), Smart-Home-Paket erforderlich:

- **URL**: die Webhook-URL von oben
- **Methode**: `GET` oder `POST`. Beides wird unterstützt; POST sendet ein JSON-Objekt.
- **Einheit / Stichwort übertragen** aktivieren. Die Standard-Parameternamen `unit` und `keyword` passen ohne Änderung.
  Wenn du sie in der App umbenennst, trage die neuen Namen in den Optionen der Integration ein.

Der aPager PRO löst Webhooks nur bei echten Alarmen aus (Reiter „Alarm“), nicht bei Info-, Unwetter- oder Statusalarmen.

**Mehrere Einheiten:** Seit aPager PRO Android 6.9.0 wird der Webhook für jede gleichzeitig alarmierte Einheit
einzeln aufgerufen. Die Integration fasst Webhooks mit gleichem Stichwort, die innerhalb von 30 Sekunden eintreffen,
zu **einem** Alarm zusammen. Webhooks ohne Stichwort (z. B. weil „Stichwort übertragen“ nur bei einer Einheit aktiv ist)
werden dabei ebenfalls dem laufenden Alarm zugeordnet und überschreiben dessen Stichwort nicht. Event, Benachrichtigung und
Zähler kommen also nur einmal. Der Sensor „Einheit“ zeigt alle alarmierten Einheiten, z. B. `LZ1, DLK`, die
**Favoriten-Einheit** (siehe Optionen) immer vorne; dieselbe Liste steht im Attribut `units`. Das Event `alamos_alarm`
enthält nur die zuerst gemeldete Einheit, weil es sofort ausgelöst wird. Wer auf alle Einheiten reagieren will, nimmt
eine Zustandsänderung des Einheiten-Sensors als Auslöser.
Probealarme und Rückalarme mehrerer Einheiten werden ebenfalls nur einmal gemeldet.

**Kommt nichts an?**

- Seit aPager PRO 6.7.1 lösen Webhooks nur aus, wenn deine FE2-Organisation das erlaubt. Frag im Zweifel deinen Admin.
- Ist der Webhook unter **Klingeltöne** (Android) bzw. **Einheitenkonfiguration → Klingeltöne** (iOS) an der richtigen Einheit aktiviert und gespeichert?
- iOS akzeptiert nur `https://`-URLs. POST gibt es unter iOS erst ab Version 1.22.0, sonst `GET` verwenden.
- URL-Platzhalter (`{unit}`, `{keyword}`) und ein eigener Header (ab aPager PRO 6.1) sind nicht nötig: Die Webhook-ID in der URL ist das Geheimnis.
- Mit **Webhook testen** in der App schickt der aPager PRO `unit1` / `B3`. Das taucht in Home Assistant als normaler Alarm auf.
- Jeder Aufruf landet im Diagnose-Sensor **Letzter Webhook** (Rohdaten und Ergebnis, im Verlauf nachvollziehbar; die
  Rohdaten nur mit der Option „Rohdaten im Verlauf speichern“). Zusätzlich schreibt die Integration jeden Aufruf ins Log, wenn du in der `configuration.yaml` Folgendes einträgst:

  ```yaml
  logger:
    logs:
      custom_components.alamos: debug
  ```
- Die Smart-Home-Funktionen (Webhooks, API) brauchen das kostenpflichtige **Smart-Home-Paket** in der App. Bei Fragen dazu hilft der Alamos-Support, nicht der Betreiber deines FE2-Systems.

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

Der Schlüssel funktioniert nur für Alarme aus dem Profil, in dem er erzeugt wurde. Bei einer **Doppelmitgliedschaft**
(z. B. Feuerwehr und Rettungsdienst) legst du die Integration einfach zweimal an, einmal pro Profil mit dem jeweiligen
Schlüssel. Ohne `config_entry_id` meldet `alamos.send_feedback` dann für alle Profile zurück.

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

> [!NOTE]
> **Keine Rückmeldung je Einheit:** Die Alamos-API kennt keinen Parameter für die Einheit oder einen einzelnen Alarm.
> Eine Zusage oder Absage gilt immer für **alle** Alarme der letzten 3 Minuten in dem Profil, zu dem der API-Schlüssel
> gehört. Werden mehrere deiner Einheiten gleichzeitig alarmiert, meldest du dich also für alle zurück. Gezielt
> unterscheiden lässt sich nur nach Profil (eigener Integrationseintrag je Profil, siehe oben). Ob du überhaupt
> zurückmeldest, kannst du aber von der Einheit abhängig machen, z. B. mit der Option „Nur bei Alarm für diese Einheit“
> im Blueprint [Automatische Rückmeldung nach Anwesenheit](#automatische-rückmeldung-nach-anwesenheit).

### Termine aus dem aPager-PRO-Kalender

Übungsdienste und andere Termine deiner Organisation lassen sich ohne diese Integration direkt in Home Assistant anzeigen:

1. In der aPager PRO App den **Kalender** öffnen → **Einstellungen** → beim gewünschten Kalender über das Drei-Punkte-Menü
   den **persönlichen iCal-Link** erzeugen und kopieren. Das geht nur, wenn dein Admin iCal-Links für den Kalender erlaubt hat.
2. In Home Assistant **Einstellungen → Geräte & Dienste → Integration hinzufügen → „Remote Calendar“** (ab Home Assistant
   2025.4) wählen und den Link eintragen.

Damit bekommst du eine Kalender-Entität, z. B. für eine Erinnerung vor dem Übungsdienst:

```yaml
triggers:
  - trigger: calendar
    event: start
    entity_id: calendar.feuerwehr_ubungsdienste
    offset: "-01:00:00"
actions:
  - action: notify.mobile_app_mein_handy
    data:
      title: "{{ trigger.calendar_event.summary }}"
      message: "Beginnt um {{ as_datetime(trigger.calendar_event.start).strftime('%H:%M') }} Uhr"
```

Behandle den iCal-Link wie ein Passwort. In der App kannst du ihn jederzeit zurücksetzen.

## Entitäten

| Entität | Beschreibung |
| --- | --- |
| `binary_sensor.<name>_alarm` | `on`, solange ein Alarm aktiv ist. Attribute: `keyword`, `unit`, `units` (alle alarmierten Einheiten, siehe „Mehrere Einheiten“), `source`, `data` (alle empfangenen Parameter, standardmäßig nicht im Verlauf gespeichert, siehe Optionen), `feedback_deadline` (bis wann eine Rückmeldung über die API möglich ist) |
| `event.<name>_alarm_event` | Event-Entität mit den Event-Typen `alarm`, `test_alarm` und `cleared` (bei `event=recall` mit `recall: true`, `keyword`, `unit`, `data`) |
| `event.<name>_alarm_event_webhook_<n>` | Event-Entität je Webhook, löst auch bei zusammengefassten Alarmen aus *(nur ab 2 Webhooks, siehe [Mehrere Webhooks](#mehrere-webhooks))* |
| `sensor.<name>_keyword` | Stichwort des letzten Alarms |
| `sensor.<name>_last_webhook` | *Diagnose.* Zeitpunkt des letzten Webhook-Aufrufs, egal ob Alarm, zusammengefasst, Probealarm, Rückalarm oder vom Einheiten-Filter ignoriert. Attribute: `received` (genauer Zeitpunkt), `webhook` (Nummer), `method`, `result` (`ok`, `merged`, `test`, `cleared`, `ignored`), `data` (Rohdaten). Im Verlauf steht damit jeder einzelne Aufruf, die Rohdaten aber nur mit der Option „Rohdaten im Verlauf speichern“ |
| `sensor.<name>_unit` | Alle Einheiten des letzten Alarms, Favoriten-Einheit zuerst (z. B. `LZ2, LZ1`). Attribute: `unit` (Haupteinheit), `units` (Liste) |
| `sensor.<name>_last_alarm` | Zeitpunkt des letzten Alarms |
| `sensor.<name>_alarm_count` | Anzahl empfangener Alarme, jeder Alarm einmal (Diagnose) |
| `sensor.<name>_alarm_count_webhook_<n>` | Anzahl Alarme je Webhook *(Diagnose, nur ab 2 Webhooks)* |
| `sensor.<name>_last_feedback` | Ergebnis der letzten API-Rückmeldung *(nur mit API-Schlüssel)* |
| `button.<name>_accept_alarm` | Alarm zusagen *(nur mit API-Schlüssel)* |
| `button.<name>_reject_alarm` | Alarm absagen *(nur mit API-Schlüssel)* |
| `button.<name>_reset_alarm_count` | Setzt den Alarmzähler und alle Webhook-Zähler auf 0 *(Konfiguration)* |

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

### `alamos.reset_alarm_count`

Setzt den Alarmzähler und alle Webhook-Zähler auf 0, z. B. per Automation zum Jahreswechsel. Mit `webhook` wird nur
der Zähler dieses Webhooks zurückgesetzt, der Alarmzähler bleibt dann unverändert.

```yaml
action: alamos.reset_alarm_count
data:
  webhook: 2              # optional, 1-5
  config_entry_id: abc123 # optional, sonst alle Einträge
```

## Events

| Event | Daten |
| --- | --- |
| `alamos_alarm` | `config_entry_id`, `name`, `keyword`, `unit`, `units`, `data`, `test` (`true` bei Probealarm), `webhook` (Nummer des Webhooks), `feedback_deadline` (ISO-Zeitstempel, Alarm + 3 Minuten) |
| `alamos_alarm_cleared` | `config_entry_id`, `name`; bei `event=recall` zusätzlich `recall: true`, `keyword`, `unit`, `webhook`, `data` |

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

Mit **Nur bei Alarm für diese Einheit** (z. B. deine Favoriten-Einheit) meldet der Blueprint nur zurück, wenn diese
Einheit mitalarmiert ist. Weil aPager PRO je Einheit einen eigenen Webhook schickt, wartet er dafür bis zu 30 Sekunden
nach dem ersten Webhook. Die Rückmeldung selbst gilt trotzdem für alle Alarme der letzten 3 Minuten (siehe Hinweis bei
der Alamos API).

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
