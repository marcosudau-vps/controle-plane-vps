---
title: Control Plane Architektur-Visualisierung
description: Diese Seite veranschaulicht die Funktionsweise und das Zusammenspiel der Selfhost Control
  Plane anhand verschiedener Diagramme.
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
service_registered: '2026-05-25'
service_metadata_updated: '2026-07-01'
generated: false
---

# Control Plane Architektur-Visualisierung

Diese Seite veranschaulicht die Funktionsweise und das Zusammenspiel der Selfhost Control Plane anhand verschiedener Diagramme.

## 1. Systemkomponenten und Datenflüsse

Das folgende Diagramm zeigt, wie Benutzer/Agenten über die CLI oder das WebUI mit der FastAPI-Anwendung interagieren, die wiederum die Postgres-Datenbank aktualisiert und Konfigurationsdateien für die Infrastruktur (wie Caddy und Docker Compose) generiert.

```mermaid
graph TD
    subgraph User & Clients
        User["Human Operator"]
        Agent["AI Agent"]
    end

    subgraph Control Plane Stack
        CLI["selfhostctl CLI"]
        API["control-api FastAPI"]
        DB[("control-plane-postgres DB")]
        WebUI["Subdomains Web UI"]
    end

    subgraph Infrastructure
        Caddy["Caddy Reverse Proxy"]
        Docker["Docker Engine / Compose"]
    end

    %% Interactions
    User -->|steuert| CLI
    Agent -->|steuert| CLI
    Agent -->|API-Calls| API
    User -->|Browser| WebUI
    
    CLI -->|HTTP Requests| API
    WebUI -->|HTTP Requests| API
    API -->|Read/Write SQL| DB
    
    %% Output Generation & Deployment
    API -->|Generiert Routen| CaddyFile["routes.caddy"]
    Caddy -->|Lädt automatisch| CaddyFile
    API -->|Prüft Stack-Pfade| ComposeConfigs["docker-compose.yml Files"]
    Docker -->|Nutzt Pfade| ComposeConfigs
```

---

## 2. Datenmodell (ER-Diagramm)

Dieses Entity-Relationship-Diagramm veranschaulicht das relationale Datenmodell in PostgreSQL. Alle Fremdschlüssel-Beziehungen sind durch entsprechende Kardinalitäten gekennzeichnet.

```mermaid
erDiagram
    SERVICES ||--o{ SERVICES_TAGS : "besitzt"
    SERVICES ||--o{ ROUTES : "definiert"
    SERVICES ||--o{ PORTS : "reserviert"
    SERVICES ||--o| RUNTIMES : "läuft_auf"
    SERVICES ||--o{ RESOURCES : "besitzt"
    SERVICES ||--o{ SKILLS : "nutzt"
    SERVICES ||--o| DOCS : "dokumentiert"
    SERVICES ||--o{ HEALTHCHECKS : "prüft"
    SERVICES ||--o{ SECRET_REFS : "referenziert"
    SERVICES ||--o{ COMMENTS : "notiert_in"

    RESOURCES ||--o{ SKILLS : "zugeordnet_zu"
    RESOURCES ||--o{ SECRET_REFS : "referenziert"

    SKILLS ||--o{ SKILL_ITEMS : "enthält"

    SERVICES {
        uuid id PK
        citext slug UK
        text title
        text description
        entity_system system
        component_type component_type
        lifecycle lifecycle
        runtime_type runtime
        boolean enabled
        smallint criticality
    }

    ROUTES {
        uuid id PK
        uuid service_id FK
        citext slug UK
        citext host
        text path_prefix
        text upstream
        boolean public
        boolean enabled
    }

    PORTS {
        uuid id PK
        uuid service_id FK
        inet bind_host
        integer host_port
        integer container_port
        text protocol
        boolean public
        boolean enabled
    }

    RUNTIMES {
        uuid id PK
        uuid service_id FK
        runtime_type runtime
        citext stack_slug
        text compose_path
        text working_directory
    }

    RESOURCES {
        uuid id PK
        uuid service_id FK
        citext slug UK
        text title
        resource_type type
        text path
        boolean persistent
        boolean backup_required
    }

    SKILLS {
        uuid id PK
        uuid service_id FK
        uuid resource_id FK
        citext slug UK
        text title
        text scope
        text directory
    }

    SKILL_ITEMS {
        uuid id PK
        uuid skill_id FK
        citext slug
        text title
        text path
    }
```

---

## 3. Zweistufiges Deployment (Sequence Diagram)

Da Änderungen an Caddy-Routen riskant sind, trennt die Control Plane die Generierung (Staging & Validierung) vom eigentlichen Deployment (Apply). Dieses Sequenzdiagramm zeigt den Ablauf beim Registrieren und Veröffentlichen einer neuen Route.

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator (Mensch/Agent)
    participant CLI as selfhostctl CLI
    participant API as control-api FastAPI
    participant DB as Postgres DB
    participant Caddy as Caddy Proxy

    Operator->>CLI: selfhostctl route add <slug>
    CLI->>API: POST /api/v1/routes
    API->>DB: Prüfe Eindeutigkeit & Speichere Route (inaktiv)
    DB-->>API: Erfolgreich gespeichert
    API-->>CLI: Erfolgreich (Zustand: Ausstehend)
    
    Operator->>CLI: selfhostctl generate caddy
    CLI->>API: POST /api/v1/generate/caddy
    API->>API: Generiere routes.caddy in .staging/
    API->>Caddy: Validiere Staging-Konfiguration (caddy validate)
    Caddy-->>API: Konfiguration ist gültig
    API-->>CLI: Staging-Generierung & Validierung OK
    
    Operator->>CLI: selfhostctl deploy caddy
    CLI->>API: POST /api/v1/deploy/caddy/apply
    API->>API: Verschiebe routes.caddy ins Live-Verzeichnis
    API->>Caddy: Caddy Config neu laden (caddy reload)
    Caddy-->>API: Reload erfolgreich
    API->>DB: Aktiviere Route (enabled=true)
    API-->>CLI: Deployment abgeschlossen
    CLI-->>Operator: Route ist live erreichbar!
```
