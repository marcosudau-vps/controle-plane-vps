# Service-Contract

`GET /api/v1/services/{slug}/contract` projiziert vorhandene Tabellen, referenzierte Unterobjekte, Profil, Aliase, Lifecycle und wirksame Regeln. `schema_version=1.0`; `revision` ist ein SHA-256 über die bereinigte Projektion. Das ETag entspricht dieser Revision. JSON ist Standard, `format=yaml` erzeugt eine Projektion ohne Schreibwirkung.

Profilrevisionen starten für fehlende Profile bei 0. PUT ersetzt die Profilfelder unter `expected_revision`; ein veralteter Wert ergibt 412. Titel/Summary/Owner/Tags werden weiter an der bestehenden Servicezeile gepflegt. Aliase ändern weder ID noch Slug oder Pfade. Alias-/Slug-Konflikte ergeben 409. Secret-Inhalte werden abgewiesen bzw. aus Altprojektionen entfernt; Secret-Referenzen bleiben sichtbar.

Beispiel: `GET /api/v1/services/example-service/contract`. Antwort: `{ "ok": true, "data": {"schema_version":"1.0", "revision":"<sha256>", "service":{"slug":"example-service", "id":"<uuid>"}, "profile":{"revision":1}, "aliases":[], "runtimes":[], "routes":[], ... } }`. Die vollständigen Felder stehen im tatsächlich erzeugten OpenAPI-Modell `TechnicalContract`.

Die folgenden Typnamen verwenden die SQLAlchemy-Darstellung; die PostgreSQL-DDL steht in `migrations/baseline.sql` und `migrations/modernization.sql`. Insbesondere entspricht DATETIME einem PostgreSQL-Timestamp.

## Persistierte Felder

### `services`

| Feld | Datentyp | Pflicht | Default / Beziehung |
|---|---|---|---|
| id | VARCHAR(36) | ja | Anwendung |
| slug | VARCHAR(80) | ja | – |
| title | VARCHAR(160) | ja | – |
| summary | TEXT | ja | Anwendung |
| system | VARCHAR(40) | ja | Anwendung |
| component_type | VARCHAR(40) | ja | Anwendung |
| lifecycle | VARCHAR(40) | ja | Anwendung |
| owner | VARCHAR(80) | ja | Anwendung |
| criticality | INTEGER | ja | Anwendung |
| status | VARCHAR(40) | ja | Anwendung |
| tags | JSON | ja | Anwendung |
| metadata_json | JSON | ja | Anwendung |
| port_base | INTEGER | nein | – |
| large_port_space | BOOLEAN | ja | Anwendung |
| caddy_protection_enabled | BOOLEAN | ja | Anwendung |
| created_at | DATETIME | ja | Anwendung |
| updated_at | DATETIME | ja | Anwendung |

### `service_profiles`

| Feld | Datentyp | Pflicht | Default / Beziehung |
|---|---|---|---|
| service_id | VARCHAR(36) | ja | –; → services.id |
| revision | INTEGER | ja | Anwendung |
| description | TEXT | ja | Anwendung |
| category | VARCHAR(80) | ja | Anwendung |
| protected | BOOLEAN | ja | Anwendung |
| archivable | BOOLEAN | ja | Anwendung |
| snapshot_supported | BOOLEAN | ja | Anwendung |
| paths | JSON | ja | Anwendung |
| created_at | DATETIME | ja | Anwendung |
| updated_at | DATETIME | ja | Anwendung |

### `service_aliases`

| Feld | Datentyp | Pflicht | Default / Beziehung |
|---|---|---|---|
| alias | VARCHAR(80) | ja | – |
| service_id | VARCHAR(36) | ja | –; → services.id |
