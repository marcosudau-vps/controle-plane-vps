---
title: 'Selfhost Control Plane: Flows, Automationen und Validatoren'
description: Docs bleiben im aktiven Dokumentationsbaum erhalten, werden aber im Archiv mitgesichert.
page_type: guide
section: services
service: control-plane
status: active
service_status: active
tags:
- services
- guide
- control-plane
- service
- api
- mcp
document_date: '2026-05-25'
service_registered: '2026-05-25'
service_metadata_updated: '2026-07-01'
generated: false
---

# Selfhost Control Plane: Flows, Automationen und Validatoren

Stand: 2026-05-25, aktualisiert 2026-07-09
Ziel: Definierte Arbeitsablaeufe fuer Menschen, Agents, Backstage und CLI.

## Grundregel

Keine direkte Aenderung an generierten Dateien.

Erlaubte Schreibwege:

- `selfhostctl`
- Selfhost Control API
- spaeter Backstage Scaffolder/Formulare
- spaeter internes WebUI

Nicht erlaubt:

- direkte Edits an generierten Caddy-Routen
- direkte Edits an generierten Backstage-Catalog-Dateien
- Routen ohne Control-Plane-Eintrag
- Services ohne Runtime-/Docs-/Healthcheck-Metadaten
- Lifecycle-Services ohne `stacks/services/<slug>/service.yaml`

## Flow 1: Neuen Dienst registrieren

Ziel: Ein neuer Dienst wird vollstaendig und konsistent angelegt.

### Ablauf

1. Nutzer/Agent startet:

```bash
selfhostctl service create
```

2. Pflichtdaten erfassen:

- slug
- title
- description
- system (`services` oder `special-purpose`; regulaere Selfhost-Dienste nutzen `services`)
- component_type
- lifecycle
- runtime
- owner
- tags

3. Runtime erfassen:

- Docker Compose oder systemd oder static
- Stack-Pfad unter `/home/marco/selfhost/stacks/services/<slug>`
- Working Directory
- Start-/Stop-/Restart-Befehle

4. Routen erfassen:

- Hostname
- Path
- Upstream
- Auth Policy

5. Ports erfassen:

- Bind Host
- Host Port
- Container Port
- Protocol
- public/internal

6. Ressourcen erfassen:

- Datenpfade
- Docker Volumes
- Datenbanken
- Backup-Relevanz

7. Secrets erfassen:

- nur Secret-Refs
- keine Werte

8. Docs/Runbook anlegen oder markieren.

9. Optional Skills registrieren:

- Component Skill Directory
- Skills Manifest

10. Validatoren ausfuehren.
11. Bei Erfolg:

- DB-Transaktion committen
- Activity Log schreiben
- Caddy generieren
- Backstage generieren
- Docs-Platzhalter generieren

### Validatoren

- `service.slug.unique`
- `service.slug.format`
- `service.required-fields`
- `runtime.valid`
- `route.host.unique`
- `route.upstream.valid`
- `port.available`
- `resource.path.allowed-root`
- `secret.no-values`
- `docs.exists-or-generated`
- `skills.directory-valid`
- `service.manifest.exists`
- `service.manifest.valid`

## Flow 2: Route hinzufuegen oder aendern

Ziel: Routen nur kontrolliert ueber Control Plane.

### Ablauf

1. Route in DB anlegen/aendern.
2. Host/Path-Eindeutigkeit pruefen.
3. Upstream pruefen.
4. Auth Policy pruefen.
5. Caddy-Staging-Datei generieren.
6. `caddy validate` gegen Staging-Konfiguration ausfuehren.
7. Bei Erfolg Apply erlauben.
8. Caddy reload.
9. Externer HTTP-Check.
10. Activity Log schreiben.

### Wichtige Regel

`generate` und `apply` sind getrennt.

```bash
selfhostctl generate caddy
selfhostctl deploy caddy
```

So kann ein Agent nicht unbemerkt eine fehlerhafte Route live setzen.

## Flow 3: Backstage-Katalog generieren

Ziel: Backstage ist Projektion der Control Plane.

### Ablauf

1. Services, Resources, APIs, Skills und Relations aus DB lesen.
2. Backstage Entities erzeugen:

- Domain
- Systems
- Components
- Resources
- APIs

3. Annotationen setzen:

- service-id
- runtime
- stack-id
- route-id
- public-url
- compose-path
- healthcheck-url
- skills-directory
- skills-manifest

4. Dateien nach Staging schreiben.
5. Backstage Catalog-Dateien syntaktisch pruefen.
6. Optional Backstage config check ausfuehren.
7. Artefakt promoten.
8. Activity Log schreiben.

### Validatoren

- `backstage.entity-name.format`
- `backstage.owner.exists`
- `backstage.system.exists`
- `backstage.no-secrets`
- `backstage.relations.valid`
- `backstage.skills-annotations.valid`

## Flow 4: Component Skills registrieren

Ziel: Dienstspezifische Agenten-Skills sauber verwalten.

### Ablauf

1. Skill-Verzeichnis registrieren:

```bash
selfhostctl skills add litellm --directory /home/marco/selfhost/stacks/services/litellm/.ai/skills
```

2. Verzeichnis pruefen.
3. Optional `skills.yaml` lesen.
4. Einzelne Skill-Ordner scannen.
5. Fuer jeden Skill pruefen:

- Ordner existiert
- `SKILL.md` existiert
- keine offensichtlichen Secrets
- Pfad liegt unter erlaubtem Service-Pfad

6. `skill_items` speichern.
7. Backstage Annotationen regenerieren.
8. Agent-Kontext aktualisieren.

### Validatoren

- `skills.directory.exists`
- `skills.directory.allowed-root`
- `skills.manifest.valid-yaml`
- `skills.item.has-skill-md`
- `skills.no-secrets`
- `skills.scope.matches-owner`

## Flow 5: Secrets rendern

Ziel: Secrets werden aus Bitwarden oder definierten Quellen in Runtime-Dateien gerendert, ohne Werte in DB/Docs/Backstage abzulegen.

### Ablauf

1. Secret-Refs aus DB lesen.
2. Provider pruefen.
3. Werte aus Provider abrufen.
4. Ziel-Datei schreiben, z.B.:

```text
/home/marco/selfhost/secrets/litellm.env
```

5. Rechte setzen:

```text
0600 marco:marco
```

6. Keine Werte ins Activity Log schreiben.
7. Nur Hash/Status speichern.

### Validatoren

- `secret.ref.exists`
- `secret.provider.available`
- `secret.target-path.allowed-root`
- `secret.target-file.permissions`
- `secret.no-values-in-db`

## Flow 6: Dienst migrieren

Ziel: Migration eines Dienstes aus Exportpaket in neuen Zielbetrieb.

### Ablauf

1. Service in Control Plane anlegen.
2. Runtime/Stack anlegen.
3. Datenpfade/Resources anlegen.
4. Secret-Refs anlegen.
5. Daten aus Export wiederherstellen.
6. Secrets rendern.
7. Dienst starten.
8. Healthchecks ausfuehren.
9. Route generieren.
10. Caddy deployen.
11. Backstage generieren.
12. Docs pruefen.
13. Activity Log und Kommentar schreiben.

### Definition of Done

- Runtime startet nach Reboot.
- Route funktioniert.
- Healthcheck gruen oder bewusst manuell.
- Backstage-Eintrag generiert.
- Runbook vorhanden.
- Ressourcen/Backups markiert.
- Keine Secrets in generierten Artefakten.

## Flow 7: Validierung komplett

Ziel: Vor Apply/Deploy wird der komplette Zustand geprueft.

```bash
selfhostctl validate all
```

Validator-Gruppen:

### Service Validatoren

- `service.slug.format`
- `service.slug.unique`
- `service.required-fields`
- `service.lifecycle.valid`
- `service.system.valid`
- `service.manifest.exists`
- `service.manifest.slug-matches-path`
- `service.manifest.compose-project-matches-slug`
- `service.manifest.paths.allowed-root`
- `service.owner.valid`
- `service.has-runtime`
- `service.has-docs`

### Route Validatoren

- `route.slug.unique`
- `route.host.format`
- `route.host-path.unique`
- `route.upstream.syntax`
- `route.auth-policy.exists`
- `route.service.exists`
- `route.public-has-auth-or-app-native`

### Port Validatoren

- `port.range`
- `port.unique-active`
- `port.real-availability`
- `port.public-declared`
- `port.route-upstream-registered`

### Runtime Validatoren

- `runtime.compose-path.exists`
- `runtime.working-directory.exists`
- `runtime.systemd-unit.exists`
- `runtime.path.allowed-root`
- `runtime.docker-compose-config-valid`

### Resource Validatoren

- `resource.slug.unique`
- `resource.path.exists-if-required`
- `resource.path.allowed-root`
- `resource.backup-policy-if-persistent`
- `resource.restore-notes-if-critical`

### Secret Validatoren

- `secret.no-secret-values`
- `secret.ref.format`
- `secret.provider.available`
- `secret.target-path.allowed-root`

### Docs Validatoren

- `docs.runbook.exists`
- `docs.required-sections`
- `docs.no-secrets`
- `docs.links-valid`

### Skills Validatoren

- `skills.directory.exists`
- `skills.manifest.valid`
- `skills.item-has-skill-md`
- `skills.no-secrets`

### Generator Validatoren

- `generated.header-present`
- `generated.no-manual-edits`
- `caddy.validate`
- `backstage.catalog-valid`

## Flow 8: Apply Guard

Ziel: Riskante Operationen blockieren, wenn der Zustand nicht sauber ist.

Vor diesen Operationen ist ein aktueller Validation Run Pflicht:

- `deploy caddy`
- `service start production`
- `lifecycle execute-archive`
- `lifecycle execute-restore`
- `route delete`
- `secrets render`
- `restore data`

Regel:

```text
Fatal/Error blockiert Apply.
Warning erlaubt Apply nur mit explizitem --ack.
```

## Flow 9: Export

Ziel: Restore-faehige Exporte aus DB erzeugen.

### Ablauf

1. Validation Run starten.
2. SQL-Dump erzeugen.
3. JSON-Export erzeugen.
4. YAML-Export erzeugen.
5. generierte Artefakte beilegen.
6. SHA256 schreiben.
7. Export Run speichern.

### Export-Inhalte

- Datenbankdump
- Service-Metadaten
- Route-Metadaten
- Backstage-Catalog
- Caddy-Routen
- Docs-Index
- Skill-Index
- Activity Log optional

## Flow 9b: Service-Lifecycle Snapshot, Archive und Restore

Ziel: Dienste mit `service.yaml` koennen kontrolliert gesichert, archiviert und wiederhergestellt werden.

### Snapshot

1. Manifest laden und validieren.
2. Inventory aus Manifest, Compose, DB-Servicebaum, Routen, Ports, Runtime, Docs, Healthchecks und Secret-Refs erzeugen.
3. Plan mit stabilem `plan_hash` berechnen.
4. Nur bei passendem `plan_hash` ausfuehren.
5. Archivpaket unter `/home/marco/selfhost/backups/service-lifecycle` schreiben.
6. Runtime bleibt unveraendert aktiv.

### Archive

1. `lifecycle.archivable` pruefen.
2. Compose-Konfiguration validieren.
3. Compose-Stack stoppen.
4. Finales Archivpaket erzeugen.
5. Service-Status auf `archived` setzen.
6. Routen und Ports auf `inactive` setzen, nicht loeschen.
7. Caddy neu generieren und validieren.
8. Stack-, Daten-, App- und Build-Pfade in die Quarantaene des Archives verschieben.
9. `lifecycle_runs` und Activity Log schreiben.

Docs bleiben im aktiven Dokumentationsbaum erhalten, werden aber im Archiv mitgesichert.

### Restore

1. Archiv inspizieren.
2. Restore-Plan erzeugen und Zielpfad-Kollisionen pruefen.
3. Nur bei passendem `plan_hash` ausfuehren.
4. Fehlende Dateien aus Archiv wiederherstellen.
5. DB-Servicebaum, Routen, Ports und Runtime wiederherstellen.
6. Service, Routen und Ports aktivieren.
7. Compose-Stack starten.
8. Caddy generieren/validieren und Healthchecks ausfuehren.

Bestehende Zielpfade blockieren Restore, ausser sie sind leer oder bewusst als Quarantaene dieses Archives bekannt.

## Flow 10: Agenten-Kontext bereitstellen

Ziel: Ein Agent bekommt vor Arbeit an einem Dienst die richtigen Regeln.

API:

```http
GET /api/v1/agent/context/service/{serviceSlug}
```

Liefert:

- Service-Zusammenfassung
- Runtime
- Routen
- Docs/Runbook
- Skill-Verzeichnisse
- relevante Validator-Warnungen
- erlaubte Aktionen
- verbotene direkte Pfade

Keine Secrets.

## Automationen

### Bei Service Create

- Docs-Platzhalter erzeugen
- Backstage neu generieren
- initiale Healthcheck-Aufgabe anlegen
- Activity Log schreiben

### Bei Route Change

- Caddy-Staging generieren
- Caddy validieren
- Backstage-Link aktualisieren
- Activity Log schreiben

### Bei Skill Change

- Skill-Scan ausfuehren
- Backstage Annotation aktualisieren
- Agent-Kontext aktualisieren

### Bei Runtime Change

- Compose/Systemd validieren
- Port-Checks ausfuehren
- Docs als "review-needed" markieren

### Taeglich

- Healthchecks laufen lassen
- Validatoren laufen lassen
- Drift pruefen:
  - Caddy-Datei entspricht Generator?
  - Backstage-Catalog entspricht Generator?
  - Ports stimmen mit laufenden Prozessen?
- Report erzeugen

## Drift Detection

Ziel: direkte manuelle Aenderungen sichtbar machen.

Pruefungen:

- Hash generierter Dateien gegen `generated_artifacts`.
- Caddyfile enthaelt nur erlaubte Imports/Sonderbloecke.
- Docker Compose Stacks entsprechen registrierten Pfaden.
- laufende Ports sind registriert oder als unmanaged markiert.
- Backstage Catalog entspricht Control Plane.

Unmanaged-Fund wird als Warning oder Error gemeldet.

## MVP-Reihenfolge

1. PostgreSQL Schema
2. Services CRUD
3. Routes/Ports CRUD
4. Runtime CRUD
5. Validation Run Framework
6. Caddy Generator
7. Backstage Generator
8. Docs Placeholder Generator
9. Skills Register/Scan
10. Activity Log
11. Export

Nicht zuerst bauen:

- grosses WebUI
- komplexe RBAC
- perfektes Backstage-Plugin
- automatische Secret-Rotation
