# Alamos (aPager PRO / AMweb) for Home Assistant

Custom integration (domain `alamos`, distributed via HACS) that receives
alarm webhooks from aPager PRO and AMweb and sends availability feedback
through the Alamos feedback API. Community project, not affiliated with
Alamos GmbH. Safety-relevant (fire brigade / EMS alerting): when in doubt,
let an alarm through rather than drop it.

## Layout (`custom_components/alamos/`)

- `__init__.py`: setup, webhook registration, services `send_feedback`
  (returns a response) and `reset_alarm`, bus events
- `receiver.py`: webhook handler (query/JSON/form payloads, clear and recall
  events, unit filter, test-alarm keywords)
- `alarm.py`: `AlamosAlarmManager` (alarm state, listeners, auto reset,
  merging of webhooks per alarm, feedback deadline)
- `api.py`: `AlamosApiClient` for the feedback API and its errors
- `config_flow.py`: config and options flow (options in `entry.options`,
  webhook ID in `entry.data`)
- Entities: `binary_sensor.py`, `event.py`, `sensor.py`, `button.py`, shared
  base in `entity.py`; constants in `const.py`
- `strings.json`, `translations/{en,de}.json`, `services.yaml`, `icons.json`,
  `brand/`
- Blueprints: `blueprints/automation/alamos/`
- Tests: `tests/test_init.py`, `tests/test_blueprints.py` (blueprints run in
  Home Assistant), `tests/test_brand.py`

## Workflow

- `scripts/setup` installs the hash-locked test dependencies,
  `scripts/test` runs Ruff check, Ruff format check and pytest (must pass
  before every PR), `scripts/develop` starts Home Assistant on port 8123,
  `scripts/lock` regenerates `requirements_test.txt`.
- The minimum Home Assistant version lives in `hacs.json`; blueprints and
  `.coderabbit.yaml` repeat it (`tests/test_min_version.py` checks that).
  The CI job `tests-min` runs pytest against it with
  `requirements_test_min.txt`; after raising it, update
  `requirements_test_min.in` and run `scripts/lock_min` (Python 3.12).
- Changes go through a pull request against `master`. Releases bump
  `version` in `manifest.json` (SemVer); `release.yml` tags and publishes
  after the merge.
- New options, entities and services are documented in `strings.json`,
  both translations and the README (German).
- Code, comments and commit messages in English; README, PR descriptions
  and German translations in German.

## graphify

`scripts/graphify` builds a code-only knowledge graph in `graphify-out/`
(git-ignored, local AST parsing, no API calls). It runs at session start;
cloud sessions install the pinned graphify release automatically. Locally,
install it with `uv tool install graphifyy==0.9.86` to use it.

When `graphify-out/graph.json` exists:

- For a codebase question, start with `graphify query "<question>"`,
  `graphify explain "<symbol>"` or `graphify path "<A>" "<B>"` before
  grepping or reading whole files, and pass this rule on to subagents that
  explore code. Read raw files for the lines the graph pointed to.
- Read `graphify-out/GRAPH_REPORT.md` only for a broad architecture
  overview.
- After changing code, run `scripts/graphify` (about two seconds) to
  refresh the graph.
