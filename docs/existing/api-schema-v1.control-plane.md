---
title: 'Selfhost Control API: API-Schema v1'
description: Der fruehere Endpoint POST /api/v1/services/{serviceSlug}/archive ist fuer echte Archivierung
  deaktiviert.
page_type: reference
section: services
service: control-plane
status: active
service_status: active
tags:
- services
- reference
- control-plane
- service
- api
- mcp
document_date: '2026-05-25'
service_registered: '2026-05-25'
service_metadata_updated: '2026-07-01'
generated: false
---

# Selfhost Control API: API-Schema v1

Stand: 2026-05-25, aktualisiert 2026-07-09
Ziel: API-Kontrakt fuer `selfhost-registry`, genutzt von `selfhostctl`, Backstage, spaeter WebUI und Agents.

## Grundsaetze

1. Die API ist der erlaubte Schreibweg in die Control Plane.
2. Backstage, CLI und Agents nutzen dieselbe API.
3. Schreiboperationen erzeugen Activity-Log-Eintraege.
4. Riskante Operationen laufen ueber Validate-Then-Apply.
5. Keine API gibt Secret-Werte aus.
6. Exporte sind abgeleitete Artefakte, nicht operative Quelle.

## Versionierung

Basis-Pfad:

```text
/api/v1
```

Breaking Changes erst mit `/api/v2`.

## Auth fuer v1

Minimal:

- API nur lokal oder hinter Caddy-Auth erreichbar.
- Token fuer `selfhostctl`/Agents spaeter ueber Secret-Ref.
- Jede Anfrage setzt `X-Actor` und optional `X-Actor-Type`.

Header:

```http
Authorization: Bearer <token>
X-Actor: marco
X-Actor-Type: human
X-Request-Id: <uuid>
```

Erlaubte Actor Types:

- `human`
- `agent`
- `system`
- `api-client`

## Standard-Response

Erfolg:

```json
{
  "ok": true,
  "data": {},
  "warnings": [],
  "requestId": "..."
}
```

Fehler:

```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Route host already exists",
    "details": {}
  },
  "requestId": "..."
}
```

## Kernobjekte

### Service

```json
{
  "id": "uuid",
  "slug": "litellm",
  "title": "LiteLLM",
  "description": "OpenAI-compatible LLM gateway.",
  "system": "services",
  "componentType": "service",
  "lifecycle": "production",
  "runtime": "docker-compose",
  "ownerRef": "user:default/marcosudau",
  "status": "active",
  "enabled": true,
  "criticality": 2,
  "tags": ["ai", "llm", "gateway", "openai-compatible"],
  "metadata": {}
}
```

### Route

```json
{
  "id": "uuid",
  "serviceId": "uuid",
  "slug": "litellm-main",
  "host": "litellm.{base_domain}",
  "pathPrefix": "/",
  "upstream": "http://127.0.0.1:4000",
  "routeType": "reverse-proxy",
  "public": true,
  "enabled": true,
  "authPolicyId": null,
  "caddyExtra": {}
}
```

### Runtime

```json
{
  "id": "uuid",
  "serviceId": "uuid",
  "runtime": "docker-compose",
  "stackSlug": "litellm",
  "composePath": "/home/marco/selfhost/stacks/services/litellm/docker-compose.yml",
  "workingDirectory": "/home/marco/selfhost/stacks/services/litellm",
  "systemdUnit": null,
  "userName": "marco"
}
```

### Resource

```json
{
  "id": "uuid",
  "serviceId": "uuid",
  "slug": "litellm-postgres",
  "title": "LiteLLM PostgreSQL",
  "type": "database",
  "path": "/home/marco/selfhost/data/services/litellm/postgresql",
  "persistent": true,
  "backupRequired": true,
  "restoreNotes": "Restore before starting litellm."
}
```

### Skill

```json
{
  "id": "uuid",
  "serviceId": "uuid",
  "slug": "litellm-component-skills",
  "title": "LiteLLM Component Skills",
  "scope": "component",
  "directory": "/home/marco/selfhost/stacks/services/litellm/.ai/skills",
  "manifestPath": "/home/marco/selfhost/stacks/services/litellm/.ai/skills/skills.yaml",
  "enabled": true
}
```

## Service-Endpunkte

### Services listen

```http
GET /api/v1/services?system=services&lifecycle=production&tag=ai
```

Response:

```json
{
  "ok": true,
  "data": {
    "items": [],
    "total": 0
  }
}
```

### Service abrufen

```http
GET /api/v1/services/{serviceSlug}
```

Optionale Includes:

```http
GET /api/v1/services/litellm?include=routes,ports,runtime,resources,apis,skills,docs,healthchecks
```

### Service anlegen

```http
POST /api/v1/services
```

Request:

```json
{
  "slug": "litellm",
  "title": "LiteLLM",
  "description": "OpenAI-compatible LLM gateway.",
  "system": "services",
  "componentType": "service",
  "lifecycle": "production",
  "runtime": "docker-compose",
  "ownerRef": "user:default/marcosudau",
  "tags": ["ai", "llm", "gateway"]
}
```

Server-seitig:

- slug validieren
- Eindeutigkeit pruefen
- Standard-Dokumentationsstatus anlegen
- Activity Log schreiben

### Service aktualisieren

```http
PATCH /api/v1/services/{serviceSlug}
```

### Service deaktivieren

```http
POST /api/v1/services/{serviceSlug}/disable
```

Der fruehere Endpoint `POST /api/v1/services/{serviceSlug}/archive` ist fuer echte Archivierung deaktiviert. Er darf hoechstens noch als Deprecated-Hinweis auf die Lifecycle-API antworten.

## Lifecycle-Endpunkte

Lifecycle-Operationen sind zweistufig: zuerst wird ein stabiler Plan erzeugt, danach wird genau dieser Plan mit passendem `plan_hash` ausgefuehrt.

```http
GET  /api/v1/lifecycle/services
GET  /api/v1/lifecycle/services/{serviceSlug}
POST /api/v1/lifecycle/services/{serviceSlug}/plan-snapshot
POST /api/v1/lifecycle/services/{serviceSlug}/execute-snapshot
POST /api/v1/lifecycle/services/{serviceSlug}/plan-archive
POST /api/v1/lifecycle/services/{serviceSlug}/execute-archive
POST /api/v1/lifecycle/archives/inspect
POST /api/v1/lifecycle/archives/{archiveId}/plan-restore
POST /api/v1/lifecycle/archives/{archiveId}/execute-restore
```

Execute-Request:

```json
{
  "plan_hash": "sha256..."
}
```

`execute-archive` darf nur funktionieren, wenn:

- `service.yaml` existiert und valide ist
- `lifecycle.archivable` true ist
- der aktuelle Plan-Hash exakt zum uebergebenen `plan_hash` passt
- `docker compose config -q` erfolgreich ist
- alle aktiven Zielpfade unter erlaubten Roots liegen

Beim Archivieren werden Routen und Ports deaktiviert, nicht geloescht. Aktive Stack-, Daten-, App- und Build-Pfade werden nach erfolgreichem Archiv in Quarantaene verschoben. Docs bleiben aktiv im Dokumentationsbaum, werden aber mitgesichert.

### `service.yaml`

Jeder Lifecycle-Service besitzt ein Manifest unter:

```text
/home/marco/selfhost/stacks/services/<serviceSlug>/service.yaml
```

Mindestfelder:

```yaml
schema_version: 1
service:
  slug: litellm
  name: LiteLLM
  category: ai
lifecycle:
  archivable: true
  snapshot_supported: true
runtime:
  backend: docker_compose
  compose_project: litellm
  compose_file: /home/marco/selfhost/stacks/services/litellm/docker-compose.yml
paths:
  stack_dir: /home/marco/selfhost/stacks/services/litellm
  data_dir: /home/marco/selfhost/data/services/litellm
  docs_dir: /home/marco/selfhost/docs/services/litellm
  config_file: /home/marco/selfhost/stacks/services/litellm/config.yaml
dependencies:
  hard: []
  optional: []
```

Nicht archivierbare Systemdienste bleiben normale registrierte Services, setzen aber `lifecycle.archivable: false`.

## Route-Endpunkte

```http
GET    /api/v1/routes
POST   /api/v1/routes
GET    /api/v1/routes/{routeSlug}
PATCH  /api/v1/routes/{routeSlug}
DELETE /api/v1/routes/{routeSlug}
```

Route anlegen:

```json
{
  "serviceSlug": "litellm",
  "slug": "litellm-main",
  "host": "litellm.{base_domain}",
  "pathPrefix": "/",
  "upstream": "http://127.0.0.1:4000",
  "public": true,
  "authPolicySlug": "app-native"
}
```

Pflichtverhalten:

- Host/Path eindeutig pruefen.
- Upstream-Syntax pruefen.
- Port aus Upstream gegen Port-Registry pruefen oder Warnung erzeugen.
- Caddy-Generierung nicht automatisch deployen, nur pending markieren.

## Port-Endpunkte

### Vorhandene Routen und Ports ändern (18.10.2026)

Die aktive API unterstützt zusätzlich authentifizierte Änderungen anhand der
Datensatz-ID. Dadurch bleiben Identität und bestehende Schutzrichtlinien bei
Portumzügen erhalten. Es erfolgt keine automatische Caddy-Generierung oder
Bereitstellung; anschließend weiterhin validieren, generieren, planen und anwenden.

```http
PATCH /api/v1/routes/{route_id}
PATCH /api/v1/ports/{port_id}
```

Route: optionale Felder `upstream`, `service_slug`, `status`.
Port: optionale Felder `number`, `service_slug`, `purpose`, `status`.
Statuswerte: `active`, `inactive`, `archived`. Nicht angegebene Felder bleiben
unverändert; explizites `null` und unbekannte Felder werden zurückgewiesen.
Portnummern müssen zwischen 1 und 65535 liegen, Upstreams absolute HTTP(S)-URLs
sein. Host, Pfad, TLS und Authentifizierungsrichtlinie einer Route werden durch
diese Endpunkte nicht verändert. Subservice-Routen können hier nicht einem
Service neu zugeordnet werden.

Beispiel für einen Portumzug:

```json
{"number": 8051}
```

Passende Route separat aktualisieren:

```json
{"upstream": "http://127.0.0.1:8051"}
```

`service_slug` ermöglicht die Übernahme eines bestehenden Port- oder
Service-Routeneintrags bei einer Dienstzusammenführung. Fehlende IDs oder
Zielservices ergeben 404, Portkonflikte 409 mit Datenbank-Rollback und
ungültige Eingaben 422. Erfolgreiche Änderungen schreiben `route.update`
beziehungsweise `port.update` ins Activity-Log. Die API ändert weder
Compose-Dateien noch laufende Container; diese müssen im selben Wartungsschritt
konsistent angepasst und geprüft werden.

```http
GET  /api/v1/ports
POST /api/v1/ports
GET  /api/v1/ports/check?host=127.0.0.1&port=4000&protocol=tcp
```

Port-Check Response:

```json
{
  "ok": true,
  "data": {
    "available": false,
    "reason": "registered",
    "serviceSlug": "litellm"
  }
}
```

## Runtime-Endpunkte

```http
GET   /api/v1/services/{serviceSlug}/runtime
PUT   /api/v1/services/{serviceSlug}/runtime
POST  /api/v1/services/{serviceSlug}/runtime/validate
```

Runtime-Validierung:

- Compose-Datei existiert.
- Working Directory existiert.
- Bei systemd: Unit existiert.
- Pfade liegen unter erlaubten Roots.

## Resource-Endpunkte

```http
GET    /api/v1/resources
POST   /api/v1/resources
GET    /api/v1/resources/{resourceSlug}
PATCH  /api/v1/resources/{resourceSlug}
DELETE /api/v1/resources/{resourceSlug}
```

## API-Entity-Endpunkte

```http
GET    /api/v1/apis
POST   /api/v1/apis
GET    /api/v1/apis/{apiSlug}
PATCH  /api/v1/apis/{apiSlug}
```

## Skills-Endpunkte

```http
GET   /api/v1/services/{serviceSlug}/skills
POST  /api/v1/services/{serviceSlug}/skills
POST  /api/v1/skills/{skillSlug}/scan
POST  /api/v1/skills/{skillSlug}/validate
```

Skill anlegen:

```json
{
  "slug": "litellm-component-skills",
  "title": "LiteLLM Component Skills",
  "scope": "component",
  "directory": "/home/marco/selfhost/stacks/services/litellm/.ai/skills",
  "manifestPath": "/home/marco/selfhost/stacks/services/litellm/.ai/skills/skills.yaml"
}
```

Scan:

- findet Skill-Ordner
- prueft `SKILL.md`
- liest optional `skills.yaml`
- schreibt `skill_items`

## Secret-Ref-Endpunkte

```http
GET  /api/v1/services/{serviceSlug}/secret-refs
POST /api/v1/services/{serviceSlug}/secret-refs
POST /api/v1/services/{serviceSlug}/secrets/render
POST /api/v1/services/{serviceSlug}/secrets/check
```

Wichtig:

- `GET` liefert keine Secret-Werte.
- `render` schreibt nur lokale Runtime-Dateien.
- `check` prueft Existenz/Erreichbarkeit der Referenz.

## Docs-Endpunkte

```http
GET  /api/v1/services/{serviceSlug}/docs
PUT  /api/v1/services/{serviceSlug}/docs
POST /api/v1/services/{serviceSlug}/docs/generate
POST /api/v1/services/{serviceSlug}/docs/validate
```

## Healthcheck-Endpunkte

```http
GET  /api/v1/services/{serviceSlug}/healthchecks
POST /api/v1/services/{serviceSlug}/healthchecks
POST /api/v1/healthchecks/run
POST /api/v1/services/{serviceSlug}/healthchecks/run
```

## Validation-Endpunkte

```http
POST /api/v1/validate
GET  /api/v1/validation-runs
GET  /api/v1/validation-runs/{runId}
```

Request:

```json
{
  "scope": "all",
  "validators": [
    "service-slugs",
    "routes",
    "ports",
    "secrets",
    "docs",
    "skills",
    "caddy",
    "backstage"
  ]
}
```

Response:

```json
{
  "ok": true,
  "data": {
    "runId": "uuid",
    "status": "failed",
    "summary": "2 errors, 3 warnings",
    "results": []
  }
}
```

## Generator-Endpunkte

```http
POST /api/v1/generate/caddy
POST /api/v1/generate/backstage
POST /api/v1/generate/docs
POST /api/v1/generate/all
GET  /api/v1/generated-artifacts
```

Generatoren schreiben zuerst in staging:

```text
/home/marco/selfhost/generated/.staging/
```

Erst nach Validierung wird nach:

```text
/home/marco/selfhost/generated/
```

promoted.

## Deploy-Endpunkte

Riskante Operationen sind zweistufig.

### Caddy deploy plan

```http
POST /api/v1/deploy/caddy/plan
```

### Caddy apply

```http
POST /api/v1/deploy/caddy/apply
```

Apply darf nur, wenn:

- letzte Caddy-Generierung erfolgreich
- Caddy-Validierung erfolgreich
- keine fatalen Validatoren offen

## Export-Endpunkte

```http
POST /api/v1/export/json
POST /api/v1/export/yaml
POST /api/v1/export/sql
GET  /api/v1/export-runs
```

Export ist Backup-/Review-Artefakt, nicht Schreibquelle.

## Activity und Kommentare

```http
GET  /api/v1/activity?entityKind=service&entitySlug=litellm
POST /api/v1/comments
GET  /api/v1/comments?entityKind=service&entitySlug=litellm
```

Kommentar:

```json
{
  "entityKind": "service",
  "entitySlug": "litellm",
  "body": "Config changed during migration; verify model routing after restore."
}
```

## Agenten-Endpunkte

Optional in v1, aber sinnvoll:

```http
GET /api/v1/agent/context/service/{serviceSlug}
GET /api/v1/agent/allowed-actions
POST /api/v1/agent/action-request
```

`agent/context` liefert:

- Service-Metadaten
- Routen
- Runtime
- Docs-Pfade
- Skill-Pfade
- Warnungen
- erlaubte Operationen

Keine Secrets.

## CLI-Abbildung

`selfhostctl` ist nur eine Huelle ueber die API:

```bash
selfhostctl service list
selfhostctl service show litellm
selfhostctl service create
selfhostctl route add litellm
selfhostctl validate
selfhostctl generate all
selfhostctl deploy caddy
selfhostctl skills scan litellm
selfhostctl lifecycle list
selfhostctl lifecycle plan-archive litellm
selfhostctl lifecycle execute-archive litellm --plan-hash <hash>
selfhostctl lifecycle snapshot litellm
selfhostctl lifecycle plan-restore <archive-id>
selfhostctl lifecycle execute-restore <archive-id> --plan-hash <hash>
selfhostctl export yaml
```

## API-MVP

Fuer den Start zwingend:

1. Services CRUD
2. Routes CRUD
3. Ports CRUD + Check
4. Runtime PUT/Validate
5. Skills Register/Scan/Validate
6. Docs Register/Generate/Validate
7. Validation Run
8. Generate Caddy
9. Generate Backstage
10. Activity Log
11. Lifecycle `plan`, `snapshot`, `archive`, `restore`
