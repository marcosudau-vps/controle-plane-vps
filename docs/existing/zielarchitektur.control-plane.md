---
title: Control Plane Zielarchitektur
description: Der neue Server bekommt keine provisorische YAML-Registry als operative Wahrheit. Stattdessen
  wird eine kleine, saubere Control Plane aufgebaut.
page_type: architecture
section: services
service: control-plane
status: active
service_status: active
tags:
- services
- architecture
- control-plane
- service
- api
- mcp
document_date: '2026-07-09'
service_registered: '2026-05-25'
service_metadata_updated: '2026-07-01'
generated: false
---

# Selfhost Control Plane: Zielarchitektur

Stand: 2026-07-09  
Status: Umgesetzt / Historische Spezifikation mit Ergänzungen

## Leitentscheidung

Der neue Server bekommt keine provisorische YAML-Registry als operative Wahrheit. Stattdessen wird eine kleine, saubere Control Plane aufgebaut.

Ziel:

```text
Selfhost Control Plane = operative Steuerungsschicht fuer Dienste, Routen, Metadaten, Validierung, Dokumentation, Agenten und Verwaltungsflows.
```

Dokumentation ist dabei nur ein Output. Die eigentliche Aufgabe ist kontrollierte Serververwaltung.

## Grundprinzipien

1. Die Control Plane ist die autoritative Quelle fuer Services, Routen, Runtime-Metadaten und Betriebsstatus.
2. Caddy-Konfiguration, Docs und Reports werden generiert.
3. Agenten und Menschen schreiben nicht direkt an Caddy, Compose oder generierte Docs vorbei.
4. YAML/JSON bleibt als Export-, Backup-, Review- und Restore-Format erhalten, aber nicht als primaere Datenhaltung.
5. Alle Schreiboperationen laufen ueber API, CLI oder das WebUI.
6. Jede Aenderung wird validiert und im Audit-/Activity-Log festgehalten.

## Komponenten

### `selfhost-registry`

Backend-Service mit Datenbank und API.

Aufgaben:

- Service-/Component-Metadaten verwalten
- Routen verwalten
- Runtime-/Stack-Informationen verwalten
- Skill-Metadaten verwalten
- Secret-Refs verwalten
- Healthcheck-Definitionen verwalten
- Dokumentationsstatus verwalten
- Activity-/Change-Log fuehren
- Validierung ausfuehren
- Generatoren anstossen

### `selfhostctl`

CLI fuer Menschen, Agents und Skripte.

Beispiele:

```bash
selfhostctl service create
selfhostctl service update litellm
selfhostctl route add litellm
selfhostctl validate
selfhostctl generate caddy
selfhostctl generate docs
selfhostctl deploy caddy
selfhostctl secrets render litellm
selfhostctl doctor
```

Regel:

```text
Agents verwenden selfhostctl oder die API. Direkte manuelle Edits an generierten Dateien sind nicht erlaubt.
```

### WebUI

Ein kleines internes WebUI. Es nutzt dieselbe API wie `selfhostctl`.

## Datenhaltung

Empfehlung: PostgreSQL.

Warum nicht nur YAML:

- mehrere Schreibwege
- API-Zugriff fuer Agents
- WebUI/Formulare
- Activity-Log
- Validierungsstatus
- flexible Metadaten
- Kommentare und Aenderungsnotizen
- Relationen zwischen Services, APIs, Ressourcen und Skills
- Transaktionen

Warum PostgreSQL statt SQLite:

- bessere gleichzeitige Schreibzugriffe
- sauberer fuer API/WebUI/Agents
- JSONB fuer flexible Metadaten
- robuste Migrationen und Dumps
- ausreichend langlebige Grundlage

SQLite waere fuer einen reinen CLI-Prototyp einfacher, aber PostgreSQL ist die bessere Basis.

## Export- und Restore-Modell

Auch wenn die Datenbank die operative Wahrheit ist, muss sie jederzeit exportierbar sein.

Pflicht-Exports:

- SQL-Dump
- JSON-Export
- YAML-Export fuer Review/Lesbarkeit
- generierte Caddy-Dateien
- generierte Docs/Runbooks

Prinzip:

```text
PostgreSQL = operative Wahrheit
Exports = nachvollziehbare Sicherung und Wiederherstellung
Generated files = abgeleitete Artefakte
```

## Datenmodell v1

Das konkrete PostgreSQL-Schema ist separat ausgearbeitet:

- [PostgreSQL-Datenbankschema](datenbankschema-v1.control-plane.md)

Der API-Kontrakt und die Betriebsablaeufe sind ebenfalls getrennt dokumentiert:

- [Control API Schema](api-schema-v1.control-plane.md)
- [Flows und Validatoren](flows-automationen-validatoren-v1.control-plane.md)

### `services`

Haupttabelle fuer betriebene Komponenten.

Pflichtfelder:

- `id`
- `name`
- `title`
- `description`
- `system`: `foundation`, `managed-services`, `special-purpose`
- `component_type`: `service`, `website`, `worker`, `tool`, `documentation`, `library`
- `lifecycle`: `experimental`, `development`, `production`, `deprecated`
- `runtime`: `docker-compose`, `host-systemd`, `user-systemd`, `static-files`, `external`
- `owner`
- `status`
- `created_at`
- `updated_at`

### `routes`

- `id`
- `service_id`
- `host`
- `path`
- `upstream`
- `public`
- `auth_policy_id`
- `enabled`
- `notes`

### `ports`

- `id`
- `service_id`
- `bind_host`
- `host_port`
- `container_port`
- `protocol`
- `purpose`
- `public`

### `stacks`

- `id`
- `service_id`
- `runtime`
- `compose_path`
- `working_directory`
- `systemd_unit`
- `start_command`
- `restart_policy`

### `resources`

Fuer Datenbanken, Volumes, Datenpfade, Hosts, Directories und externe Abhaengigkeiten.

- `id`
- `name`
- `type`
- `service_id`
- `path`
- `backup_relevance`
- `restore_notes`
- `persistent`

### `apis`

- `id`
- `service_id`
- `name`
- `type`
- `description`
- `definition_path`
- `public_url`
- `lifecycle`

### `dependencies`

Relationen zwischen Services, Resources und APIs.

- `source_ref`
- `target_ref`
- `relation_type`: `depends_on`, `provides_api`, `consumes_api`, `owns`, `uses`

### `skills`

Komponentenbezogene Agenten-Skills.

- `id`
- `service_id`
- `scope`: `component`, `foundation`, `shared`
- `title`
- `description`
- `directory`
- `manifest_path`
- `enabled`

### `skill_items`

Optional aus `skills.yaml` oder Verzeichnis-Scan abgeleitet.

- `id`
- `skill_id`
- `title`
- `path`
- `purpose`
- `applies_to`

### `secret_refs`

Keine Secret-Werte, nur Referenzen.

- `id`
- `service_id`
- `provider`: `bitwarden`, `file`, `manual`
- `ref`
- `purpose`
- `required`

### `docs`

- `id`
- `service_id`
- `runbook_path`
- `techdocs_path`
- `required`
- `status`
- `last_checked_at`

### `healthchecks`

- `id`
- `service_id`
- `type`: `http`, `tcp`, `command`
- `target`
- `expected_status`
- `enabled`

### `activity_log`

Append-only Log fuer Aenderungen.

- `id`
- `actor`
- `actor_type`: `human`, `agent`, `system`
- `action`
- `entity_type`
- `entity_id`
- `summary`
- `before`
- `after`
- `created_at`

### `comments`

Kurze Betriebsnotizen pro Entity.

- `id`
- `entity_type`
- `entity_id`
- `author`
- `body`
- `created_at`

## Component Skills

Das Skill-Konzept wird uebernommen und als eigener Teil der Control Plane verstanden.

### Component Skills

Skills, die direkt zu einer Component gehoeren.

Beispiel:

```text
/home/marco/selfhost/stacks/managed-services/litellm/.ai/skills/
  litellm-routing-debugging/
    SKILL.md
  litellm-config-change-workflow/
    SKILL.md
```

Zweck:

- konkrete Workflows
- dienstspezifische Warnungen
- Bedienhinweise
- Debugging-Regeln
- Update-/Deploy-Regeln
- bekannte Stolperfallen

### Foundation Skills

Component Skills fuer kritische Foundation-Komponenten:

- `caddy`
- `docker-host`
- `selfhost-registry`
- `serverdocs`

Diese Skills sind besonders wichtig, weil sie Agenten begrenzen und korrekte Ablaeufe erzwingen.

### Shared Skills

Allgemeine Skill-Sammlungen fuer AI-/Agenten-Dienste. Diese werden als Resource modelliert, nicht als Component Skill einer einzelnen Anwendung.

Beispiel:

```text
/home/marco/selfhost/shared-ai-skills/
```

## Generatoren

Die Control Plane erzeugt:

- Caddy-Routen
- Service-Dokumentation/Runbook-Platzhalter
- Portlisten
- Backup-/Restore-Reports
- Healthcheck-Listen
- Agenten-Kontextdateien

Generierte Dateien bekommen einen Header:

```text
Generated by selfhost-registry. Do not edit manually.
```

## Validatoren

Pflichtvalidierungen:

- Service-ID eindeutig
- Hostname eindeutig
- Route eindeutig
- Port nicht belegt
- Upstream plausibel
- Compose-Datei vorhanden
- Systemd-Unit vorhanden, falls runtime `user-systemd` oder `host-systemd`
- keine Secrets in Docs/Generated Files
- Docs/Runbook vorhanden oder bewusst als fehlend markiert
- Skill-Pfade existieren, wenn registriert
- Caddy-Konfiguration validiert

## Agenten-Governance

Agenten duerfen:

- `selfhostctl` verwenden
- die Control-Plane-API verwenden
- nicht-generierte Service-Quellen bearbeiten, wenn Aufgabe es verlangt

Agenten duerfen nicht:

- generierte Caddy-Dateien manuell editieren
- Secrets in Docs schreiben
- Ports/Routen ohne Registry-Eintrag anlegen
- Services ohne Runbook/Metadaten starten

Diese Regeln gehoeren in:

- `AGENTS.md`
- Control-Plane-Validator
- ggf. Dateirechte/Preflight-Checks

## Migrationseinordnung

Reihenfolge:

1. PostgreSQL fuer Control Plane starten.
2. `selfhost-registry` Backend mit Migrationen aufsetzen.
3. `selfhostctl` CLI aufsetzen.
4. Basisdatenmodell anlegen.
5. Generatoren fuer Caddy minimal, aber sauber bauen.
6. Validatoren fuer Namen, Ports, Routen, Secrets, Docs bauen.
7. Erste Foundation-Components eintragen.
8. Danach Dienste migrieren.

## Bewusste Nicht-Ziele fuer v1

Nicht sofort noetig:

- komplexe Rechteverwaltung
- grosses WebUI
- vollautomatische Secret-Rotation
- vollstaendige Monitoring-Integration

Aber die Architektur muss diese Dinge spaeter sauber aufnehmen koennen.

## Schlussfolgerung

Die Control Plane ist der richtige Ort, um Serververwaltung, Routen, Docs, Skills, Validierung und Agentensteuerung zusammenzufuehren. Sie bildet eine langlebige Grundlage fuer den Systembetrieb.
