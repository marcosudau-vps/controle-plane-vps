---
title: Control Plane
description: Die Selfhost Control Plane ist die operative Verwaltungsschicht fuer Services, Routen, Ports,
  Runtime-Informationen, Dokumentationsreferenzen, Healthchecks, Validierung und…
page_type: overview
section: services
service: control-plane
status: active
service_status: active
tags:
- services
- overview
- control-plane
- service
- api
- mcp
service_registered: '2026-05-25'
service_metadata_updated: '2026-07-01'
generated: false
---

# Control Plane

Die Selfhost Control Plane ist die operative Verwaltungsschicht fuer Services, Routen, Ports, Runtime-Informationen, Dokumentationsreferenzen, Healthchecks, Validierung und Caddy-Artefakte.

## Aktueller Zielstand

Die Control Plane laeuft vollstaendig in Docker:

```text
/home/marco/selfhost/stacks/services/control-plane
```

Container:

| Container | Zweck |
|---|---|
| `control-plane` | FastAPI-App, `selfhostctl`, Generatoren, Subdomains-Web-UI |
| `control-plane-postgres` | operative PostgreSQL-Datenbank der Control Plane |

Die API lauscht im Container auf `8765`; der Host-Port wird im Compose-Stack ueber `CONTROL_PLANE_HOST_PORT` gesetzt. Auf diesem Host ist aktuell `127.0.0.1:8765` gebunden. Caddy routet die Subdomains-Web-UI ueber diesen lokalen Upstream.

## Source und Build

Die Codebasis bleibt schlank unter:

```text
/home/marco/selfhost/apps/services/control-plane
```

Build, Test, Entwicklungs-venv und Docker-Image-Build laufen ueber die Build Area:

```text
/home/marco/selfhost_outsourced/build_area/services/control-plane
```

Wichtige Pfade:

| Pfad | Bedeutung |
|---|---|
| `apps/services/control-plane` | Source-Code |
| `build_area/services/control-plane/workdir` | synchronisierte Arbeitskopie |
| `build_area/services/control-plane/workdir/.venv` | Entwicklungs-venv |
| `stacks/services/control-plane/docker-compose.yml` | produktiver Docker-Stack |

Das produktive Image ist `selfhost/control-plane:build-area` und wird aus dem Build-Area-`workdir` gebaut.

## Bestandteile

Zur Control Plane gehoeren aktuell:

- FastAPI-basierte Control API
- `selfhostctl` als CLI/API-Client
- Subdomains-Web-UI unter `/subdomains`
- Caddy-Routengenerierung
- Auto-Cert-Zones als integriertes Python-Modul
- Service-Lifecycle fuer `plan`, `snapshot`, `archive` und `restore`
- eigene PostgreSQL-Datenbank im Docker-Stack

Die Control Plane ist die operative Quelle fuer Service-Metadaten wie Service-Slug, System, Runtime, Route, Dokumentationsreferenz und Healthcheck. Neue regulaere Subdomains werden als Route registriert und danach als Caddy-Artefakt generiert; generierte Caddy-Dateien werden nicht manuell editiert.

Nicht mehr Teil des Control-Plane-Kerns ist die Backstage-Kataloggenerierung. Diese Logik ist uebergangsweise in den Backstage-Bereich ausgelagert.

## Browser-Zugriff

Die Control-Plane-Domain ist ueber Caddy-Schutz abgesichert. Browser ohne gueltige Session werden zur Login-Seite unter `/caddy-schutz/login` geleitet.

- Swagger UI: `https://control-plane.marcosudau.com/docs`
- ReDoc: `https://control-plane.marcosudau.com/redoc`
- OpenAPI JSON: `https://control-plane.marcosudau.com/openapi.json`

## Service-Lifecycle

Lifecycle-Operationen werden ueber eigene Control-Plane-Module unter `control_plane/lifecycle/` bereitgestellt. Grundlage ist je Service ein Manifest:

```text
/home/marco/selfhost/stacks/services/<slug>/service.yaml
```

Unterstuetzte Operationen:

| Operation | Zweck |
|---|---|
| `plan-snapshot` / `execute-snapshot` | nicht-destruktives Archiv des aktuellen Service-Zustands |
| `plan-archive` / `execute-archive` | Stack stoppen, Archiv erzeugen, Routen/Ports deaktivieren, aktive Pfade in Quarantaene verschieben |
| `inspect` / `plan-restore` / `execute-restore` | Archiv pruefen, Restore planen, Dateien und DB-Zustand wiederherstellen |

Archive liegen unter:

```text
/home/marco/selfhost/backups/service-lifecycle
```

`execute-archive` loescht keine aktiven Pfade direkt. Stack-, Daten-, App- und Build-Area-Pfade werden nach erfolgreichem Archiv in die Quarantaene des Archives verschoben. Dokumentationspfade bleiben aktiv, werden aber mitgesichert.

Nicht archivierbare Systemdienste bleiben registrierte Services mit Manifest, setzen aber `lifecycle.archivable: false`. Aktuell betrifft das `caddy`, `control-plane`, `docs-site`, `bulwark` und `stalwart`.

## Betrieb

```bash
docker compose -f /home/marco/selfhost/stacks/services/control-plane/docker-compose.yml ps
curl -fsS http://127.0.0.1:${CONTROL_PLANE_HOST_PORT:-8765}/health
/home/marco/selfhost/tools/selfhostctl doctor
/home/marco/selfhost/tools/selfhostctl validate --scope all
/home/marco/selfhost/tools/selfhostctl lifecycle list
/home/marco/selfhost/tools/selfhostctl lifecycle plan-archive dozzle
```

## Entwicklung und Build

```bash
cd /home/marco/selfhost_outsourced/build_area/services/control-plane
./build.sh
```

Der Build-Job fuehrt aus:

1. Precheck
2. Source-Sicherung
3. Sync nach `workdir`
4. venv-Reparatur und editable Install
5. Pytest
6. Docker-Build `selfhost/control-plane:build-area`

Nach einem neuen Build muss `control-plane` recreated werden, damit der Container das neue Image nutzt.
