---
title: 'Selfhost Control Plane: PostgreSQL-Datenbankschema'
description: YAML/JSON-Dateien sind nur Export-, Review-, Backup- und Restore-Format.
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

# Selfhost Control Plane: PostgreSQL-Datenbankschema

Stand: 2026-05-25, aktualisiert 2026-07-09
Ziel: Operative Datenhaltung fuer `selfhost-registry` / `selfhost-control-api`.

## Designziele

Die Datenbank ist die operative Wahrheit fuer:

- Services / Components
- Routen
- Ports
- Runtime-/Stack-Metadaten
- Ressourcen / persistente Daten
- APIs
- Abhaengigkeiten
- Component Skills und Shared Skills
- Secret-Referenzen
- Dokumentationsstatus
- Healthchecks
- Validierungsstatus
- Activity Log und Kommentare
- Generator-/Deployment-Artefakte

YAML/JSON-Dateien sind nur Export-, Review-, Backup- und Restore-Format.

## Schema-Namespace

Empfehlung:

```sql
CREATE SCHEMA IF NOT EXISTS selfhost;
```

Alle Tabellen liegen unter `selfhost`.

## Erweiterungen

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
```

`pgcrypto` fuer UUIDs, `citext` fuer case-insensitive Hostnames/IDs falls benoetigt.

## Enumerationen

```sql
CREATE TYPE selfhost.entity_system AS ENUM (
  'services',
  'special-purpose'
);

CREATE TYPE selfhost.lifecycle AS ENUM (
  'experimental',
  'development',
  'production',
  'deprecated',
  'archived'
);

CREATE TYPE selfhost.component_type AS ENUM (
  'service',
  'website',
  'worker',
  'tool',
  'documentation',
  'library'
);

CREATE TYPE selfhost.runtime_type AS ENUM (
  'docker-compose',
  'host-systemd',
  'user-systemd',
  'static-files',
  'external'
);

CREATE TYPE selfhost.resource_type AS ENUM (
  'database',
  'cache',
  'storage',
  'host',
  'network',
  'directory',
  'secret-store',
  'external-service',
  'runtime',
  'volume',
  'file'
);

CREATE TYPE selfhost.api_type AS ENUM (
  'openapi',
  'grpc',
  'graphql',
  'asyncapi',
  'websocket',
  'sse',
  'http',
  'internal',
  'other'
);

CREATE TYPE selfhost.relation_type AS ENUM (
  'depends-on',
  'provides-api',
  'consumes-api',
  'owns',
  'uses',
  'routes-to',
  'stores-data-in'
);

CREATE TYPE selfhost.auth_policy_type AS ENUM (
  'none',
  'app-native',
  'basic-auth',
  'caddy-cookie-token',
  'forward-auth',
  'oauth-proxy',
  'manual'
);

CREATE TYPE selfhost.secret_provider AS ENUM (
  'bitwarden',
  'file',
  'manual',
  'environment',
  'external'
);

CREATE TYPE selfhost.healthcheck_type AS ENUM (
  'http',
  'tcp',
  'command',
  'docker-health',
  'manual'
);

CREATE TYPE selfhost.validation_severity AS ENUM (
  'info',
  'warning',
  'error',
  'fatal'
);

CREATE TYPE selfhost.validation_status AS ENUM (
  'pending',
  'passed',
  'warning',
  'failed',
  'skipped'
);

CREATE TYPE selfhost.actor_type AS ENUM (
  'human',
  'agent',
  'system',
  'api-client'
);
```

## Gemeinsame Regeln

IDs:

- technische Primaerschluessel: `uuid`
- stabile fachliche IDs: `slug`, lowercase-kebab-case

Konvention:

```text
id = UUID
slug = stabiler maschinenlesbarer Name
title = menschenlesbarer Name
```

Warum beides:

- UUIDs sind robust fuer Foreign Keys.
- Slugs sind gut fuer CLI, URLs, Backstage und Menschen.

## Tabellen

### `services`

Zentrale Tabelle fuer Components/Hauptdienste.

```sql
CREATE TABLE selfhost.services (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug citext NOT NULL UNIQUE,
  title text NOT NULL,
  description text NOT NULL DEFAULT '',
  system selfhost.entity_system NOT NULL DEFAULT 'services',
  component_type selfhost.component_type NOT NULL DEFAULT 'service',
  lifecycle selfhost.lifecycle NOT NULL DEFAULT 'experimental',
  runtime selfhost.runtime_type NOT NULL,
  owner_ref text NOT NULL DEFAULT 'user:default/marcosudau',
  status text NOT NULL DEFAULT 'planned',
  enabled boolean NOT NULL DEFAULT true,
  criticality smallint NOT NULL DEFAULT 3 CHECK (criticality BETWEEN 1 AND 5),
  sort_order integer NOT NULL DEFAULT 1000,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz
);

CREATE INDEX services_system_idx ON selfhost.services(system);
CREATE INDEX services_lifecycle_idx ON selfhost.services(lifecycle);
CREATE INDEX services_runtime_idx ON selfhost.services(runtime);
CREATE INDEX services_metadata_gin_idx ON selfhost.services USING gin(metadata);
```

`criticality`:

- `1`: kritisch, Ausfall betrifft Betrieb/Mail/Proxy/Control Plane
- `2`: wichtig
- `3`: normal
- `4`: niedrig
- `5`: experimentell/unkritisch

### `service_tags`

Tags bewusst separat, damit sie validierbar und suchbar bleiben.

```sql
CREATE TABLE selfhost.service_tags (
  service_id uuid NOT NULL REFERENCES selfhost.services(id) ON DELETE CASCADE,
  tag text NOT NULL,
  PRIMARY KEY (service_id, tag),
  CHECK (tag ~ '^[a-z0-9][a-z0-9-]*[a-z0-9]$' OR tag ~ '^[a-z0-9]$')
);

CREATE INDEX service_tags_tag_idx ON selfhost.service_tags(tag);
```

### `auth_policies`

Auth-Beschreibung ohne Secrets.

```sql
CREATE TABLE selfhost.auth_policies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug citext NOT NULL UNIQUE,
  title text NOT NULL,
  type selfhost.auth_policy_type NOT NULL,
  description text NOT NULL DEFAULT '',
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

`config` darf keine Secret-Werte enthalten, nur Referenzen.

### `routes`

Routen fuer Caddy und Backstage-Links.

```sql
CREATE TABLE selfhost.routes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  service_id uuid NOT NULL REFERENCES selfhost.services(id) ON DELETE CASCADE,
  slug citext NOT NULL UNIQUE,
  host citext NOT NULL,
  path_prefix text NOT NULL DEFAULT '/',
  upstream text NOT NULL,
  route_type text NOT NULL DEFAULT 'reverse-proxy',
  public boolean NOT NULL DEFAULT true,
  enabled boolean NOT NULL DEFAULT true,
  auth_policy_id uuid REFERENCES selfhost.auth_policies(id),
  caddy_extra jsonb NOT NULL DEFAULT '{}'::jsonb,
  notes text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (host, path_prefix),
  CHECK (path_prefix LIKE '/%')
);

CREATE INDEX routes_service_id_idx ON selfhost.routes(service_id);
CREATE INDEX routes_host_idx ON selfhost.routes(host);
CREATE INDEX routes_enabled_idx ON selfhost.routes(enabled);
```

### `ports`

Portreservierung und Publizierung.

```sql
CREATE TABLE selfhost.ports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  service_id uuid NOT NULL REFERENCES selfhost.services(id) ON DELETE CASCADE,
  bind_host inet,
  host_port integer NOT NULL CHECK (host_port BETWEEN 1 AND 65535),
  container_port integer CHECK (container_port BETWEEN 1 AND 65535),
  protocol text NOT NULL DEFAULT 'tcp' CHECK (protocol IN ('tcp', 'udp')),
  purpose text NOT NULL DEFAULT '',
  public boolean NOT NULL DEFAULT false,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ports_unique_enabled_idx
  ON selfhost.ports (COALESCE(bind_host::text, '*'), host_port, protocol)
  WHERE enabled = true;

CREATE INDEX ports_service_id_idx ON selfhost.ports(service_id);
```

### `runtimes`

Konkrete Start-/Betriebsform eines Dienstes.

```sql
CREATE TABLE selfhost.runtimes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  service_id uuid NOT NULL REFERENCES selfhost.services(id) ON DELETE CASCADE,
  runtime selfhost.runtime_type NOT NULL,
  stack_slug citext,
  compose_path text,
  working_directory text,
  systemd_unit text,
  user_name text,
  start_command text,
  stop_command text,
  restart_command text,
  health_command text,
  restart_policy text,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (service_id, runtime, COALESCE(stack_slug, ''))
);

CREATE INDEX runtimes_service_id_idx ON selfhost.runtimes(service_id);
```

### `resources`

Persistente und technische Ressourcen.

```sql
CREATE TABLE selfhost.resources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  service_id uuid REFERENCES selfhost.services(id) ON DELETE SET NULL,
  slug citext NOT NULL UNIQUE,
  title text NOT NULL,
  type selfhost.resource_type NOT NULL,
  description text NOT NULL DEFAULT '',
  path text,
  docker_volume_name text,
  external_ref text,
  persistent boolean NOT NULL DEFAULT false,
  backup_required boolean NOT NULL DEFAULT false,
  backup_policy text,
  restore_notes text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX resources_service_id_idx ON selfhost.resources(service_id);
CREATE INDEX resources_type_idx ON selfhost.resources(type);
```

### `apis`

Backstage-API-Entities und technische Schnittstellen.

```sql
CREATE TABLE selfhost.apis (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  service_id uuid REFERENCES selfhost.services(id) ON DELETE CASCADE,
  slug citext NOT NULL UNIQUE,
  title text NOT NULL,
  description text NOT NULL DEFAULT '',
  type selfhost.api_type NOT NULL,
  lifecycle selfhost.lifecycle NOT NULL DEFAULT 'experimental',
  public_url text,
  definition_path text,
  definition_inline text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX apis_service_id_idx ON selfhost.apis(service_id);
CREATE INDEX apis_type_idx ON selfhost.apis(type);
```

### `relations`

Generisches Relationsmodell fuer Backstage und Control Plane.

```sql
CREATE TABLE selfhost.relations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_kind text NOT NULL,
  source_id uuid NOT NULL,
  relation selfhost.relation_type NOT NULL,
  target_kind text NOT NULL,
  target_id uuid NOT NULL,
  notes text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_kind, source_id, relation, target_kind, target_id)
);

CREATE INDEX relations_source_idx ON selfhost.relations(source_kind, source_id);
CREATE INDEX relations_target_idx ON selfhost.relations(target_kind, target_id);
```

Erlaubte `kind`-Werte v1:

- `service`
- `resource`
- `api`
- `route`
- `skill`

### `skills`

Skill-Verzeichnisse, die einer Component oder einer Shared Resource zugeordnet sind.

```sql
CREATE TABLE selfhost.skills (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  service_id uuid REFERENCES selfhost.services(id) ON DELETE CASCADE,
  resource_id uuid REFERENCES selfhost.resources(id) ON DELETE CASCADE,
  slug citext NOT NULL UNIQUE,
  title text NOT NULL,
  scope text NOT NULL CHECK (scope IN ('component', 'system', 'shared')),
  description text NOT NULL DEFAULT '',
  directory text NOT NULL,
  manifest_path text,
  enabled boolean NOT NULL DEFAULT true,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (service_id IS NOT NULL AND resource_id IS NULL)
    OR (service_id IS NULL AND resource_id IS NOT NULL)
  )
);

CREATE INDEX skills_service_id_idx ON selfhost.skills(service_id);
CREATE INDEX skills_resource_id_idx ON selfhost.skills(resource_id);
```

### `skill_items`

Einzelne Skills innerhalb eines Skill-Verzeichnisses.

```sql
CREATE TABLE selfhost.skill_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  skill_id uuid NOT NULL REFERENCES selfhost.skills(id) ON DELETE CASCADE,
  slug citext NOT NULL,
  title text NOT NULL,
  path text NOT NULL,
  purpose text NOT NULL DEFAULT '',
  applies_to text[] NOT NULL DEFAULT '{}',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (skill_id, slug)
);
```

### `secret_refs`

Nur Referenzen, keine Werte.

```sql
CREATE TABLE selfhost.secret_refs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  service_id uuid REFERENCES selfhost.services(id) ON DELETE CASCADE,
  resource_id uuid REFERENCES selfhost.resources(id) ON DELETE CASCADE,
  slug citext NOT NULL UNIQUE,
  provider selfhost.secret_provider NOT NULL,
  ref text NOT NULL,
  purpose text NOT NULL DEFAULT '',
  required boolean NOT NULL DEFAULT true,
  target_env_file text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (service_id IS NOT NULL OR resource_id IS NOT NULL)
);
```

### `docs`

Dokumentationsstatus und Pfade.

```sql
CREATE TABLE selfhost.docs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  service_id uuid NOT NULL REFERENCES selfhost.services(id) ON DELETE CASCADE,
  runbook_path text,
  techdocs_path text,
  required boolean NOT NULL DEFAULT true,
  status text NOT NULL DEFAULT 'missing',
  last_checked_at timestamptz,
  notes text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (service_id)
);
```

### `healthchecks`

```sql
CREATE TABLE selfhost.healthchecks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  service_id uuid NOT NULL REFERENCES selfhost.services(id) ON DELETE CASCADE,
  slug citext NOT NULL,
  type selfhost.healthcheck_type NOT NULL,
  target text NOT NULL,
  expected_status integer,
  timeout_seconds integer NOT NULL DEFAULT 10,
  enabled boolean NOT NULL DEFAULT true,
  last_status text,
  last_checked_at timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (service_id, slug)
);
```

### `validation_runs`

```sql
CREATE TABLE selfhost.validation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scope text NOT NULL DEFAULT 'all',
  status selfhost.validation_status NOT NULL DEFAULT 'pending',
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  actor text NOT NULL DEFAULT 'system',
  summary text NOT NULL DEFAULT '',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
```

### `validation_results`

```sql
CREATE TABLE selfhost.validation_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES selfhost.validation_runs(id) ON DELETE CASCADE,
  validator text NOT NULL,
  severity selfhost.validation_severity NOT NULL,
  status selfhost.validation_status NOT NULL,
  entity_kind text,
  entity_id uuid,
  code text NOT NULL,
  message text NOT NULL,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX validation_results_run_idx ON selfhost.validation_results(run_id);
CREATE INDEX validation_results_entity_idx ON selfhost.validation_results(entity_kind, entity_id);
```

### `generated_artifacts`

Dokumentiert, welche Dateien aus der Control Plane erzeugt wurden.

```sql
CREATE TABLE selfhost.generated_artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_type text NOT NULL,
  path text NOT NULL,
  checksum_sha256 text,
  generated_by text NOT NULL DEFAULT 'selfhost-registry',
  generated_at timestamptz NOT NULL DEFAULT now(),
  source_validation_run_id uuid REFERENCES selfhost.validation_runs(id),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (artifact_type, path)
);
```

### `activity_log`

Append-only.

```sql
CREATE TABLE selfhost.activity_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor text NOT NULL,
  actor_type selfhost.actor_type NOT NULL,
  action text NOT NULL,
  entity_kind text,
  entity_id uuid,
  summary text NOT NULL,
  before jsonb,
  after jsonb,
  request_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX activity_log_entity_idx ON selfhost.activity_log(entity_kind, entity_id);
CREATE INDEX activity_log_created_at_idx ON selfhost.activity_log(created_at DESC);
```

### `comments`

```sql
CREATE TABLE selfhost.comments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_kind text NOT NULL,
  entity_id uuid NOT NULL,
  author text NOT NULL,
  body text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX comments_entity_idx ON selfhost.comments(entity_kind, entity_id);
```

### `export_runs`

```sql
CREATE TABLE selfhost.export_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  export_type text NOT NULL,
  target_path text NOT NULL,
  status text NOT NULL DEFAULT 'pending',
  checksum_sha256 text,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  actor text NOT NULL DEFAULT 'system',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
```

### `lifecycle_runs`

Audit- und Ergebnisprotokoll fuer Snapshot-, Archive- und Restore-Laeufe.

```sql
CREATE TABLE selfhost.lifecycle_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  service_slug citext NOT NULL,
  action text NOT NULL CHECK (action IN ('snapshot', 'archive', 'restore')),
  status text NOT NULL DEFAULT 'planned',
  plan_hash text NOT NULL DEFAULT '',
  archive_dir text NOT NULL DEFAULT '',
  archive_path text NOT NULL DEFAULT '',
  quarantine_dir text NOT NULL DEFAULT '',
  request_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  result_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  error text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX lifecycle_runs_service_slug_idx ON selfhost.lifecycle_runs(service_slug);
CREATE INDEX lifecycle_runs_created_at_idx ON selfhost.lifecycle_runs(created_at DESC);
```

Archive selbst liegen nicht in der Datenbank, sondern unter:

```text
/home/marco/selfhost/backups/service-lifecycle/<service-slug>/<run-id>/
```

Das Archivverzeichnis enthaelt `archive.tar.zst` sowie JSON-Metadaten: `manifest.json`, `service.yaml`, `inventory.json`, `db-export.json`, `plan.json`, `checksums.json`, `path-metadata.json` und `restore-plan.json`.

## Updated-at Trigger

```sql
CREATE OR REPLACE FUNCTION selfhost.touch_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

Auf alle Tabellen mit `updated_at` anwenden.

Beispiel:

```sql
CREATE TRIGGER services_touch_updated_at
BEFORE UPDATE ON selfhost.services
FOR EACH ROW EXECUTE FUNCTION selfhost.touch_updated_at();
```

## Validierungsregeln auf DB-Ebene

Die Datenbank erzwingt:

- eindeutige Service-Slugs
- eindeutige Routen-Slugs
- eindeutige Host/Path-Routen
- eindeutige aktive Host-Port/Protocol-Kombinationen
- gueltige Enum-Werte
- keine Skill-Zuordnung gleichzeitig zu Service und Resource
- keine Secret-Refs ohne Service oder Resource
- Lifecycle-Run-Protokolle fuer ausgefuehrte Snapshot-/Archive-/Restore-Aktionen

Nicht nur in DB erzwingen:

- existiert Compose-Datei?
- ist Port real frei?
- ist Hostname DNS-seitig korrekt?
- enthaelt Text ein Secret?
- validiert Caddy?
- validiert Backstage?
- funktioniert Healthcheck?

Diese Regeln gehoeren in Validatoren der Control API.

## Initiale Seed-Daten

Mindestdaten:

- `auth_policies`: `none`, `app-native`, `caddy-cookie-token`
- Kern-Services:
  - `control-plane`
  - `selfhostctl`
  - `caddy`
  - `backstage`
  - `docker-host`
  - `docs-site`
- Resources:
  - `control-plane-postgres`
  - `selfhost-root-directory`
  - `caddy-certificates`

Die fruehere fachliche Trennung `foundation`/`managed-services` ist entfernt. Normale Selfhost-Services verwenden `system = 'services'`; direkt auf dem Host laufende Sonderdienste ohne Selfhost-Servicewurzel koennen `special-purpose` bleiben.
