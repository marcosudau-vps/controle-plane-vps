# API: services

## Endpunkte

| Methode | Pfad | JSON-Requestschema | Parameter | dokumentierte Statuscodes | Zugang |
|---|---|---|---|---|---|
| GET | `/api/v1/services` | – | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/services` | ServiceCreate | – | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/services/{slug}` | – | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| PATCH | `/api/v1/services/{slug}` | ServiceUpdate | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| DELETE | `/api/v1/services/{slug}` | – | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/services/{slug}/tree` | – | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/services/{slug}/archive` | – | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/subservices` | – | parent_type (query), parent_id (query) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/subservices` | SubServiceCreate | – | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/subservices/{slug}` | – | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| PATCH | `/api/v1/subservices/{slug}` | SubServiceUpdate | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| DELETE | `/api/v1/subservices/{slug}` | – | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/subservices/{slug}/tree` | – | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/managed-services/provision` | ManagedServiceProvisionCreate | – | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/catalog` | – | offset (query), limit (query) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/services/{slug}/contract` | – | slug (path), format (query) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/services/{slug}/profile` | – | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| PUT | `/api/v1/services/{slug}/profile` | ProfileUpdate | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| POST | `/api/v1/services/{slug}/aliases` | AliasInput | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| POST | `/api/v1/services/{slug}/metadata/plan` | MetadataInput | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| POST | `/api/v1/services/{slug}/metadata/import` | MetadataInput | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| POST | `/api/v1/services/{slug}/dependencies` | DependencyInput | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/services/{slug}/metadata/export` | – | slug (path), format (query) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |

Request-Feldtypen, Pflichtfelder, Enums und Antworten stehen in [OpenAPI](openapi.json). Die Contractseiten beschreiben Beziehungen, Fehler und Kompatibilität. Keine hier aufgeführte Route ist nur als zukünftiger Platzhalter dokumentiert.

## Bewusste Kompatibilitätsgrenzen

Das bestehende DELETE eines Services ist jetzt strenger: geschützte Services ergeben 403. Vor dem Löschen muss der Registryzustand `archived` sein und ein erfolgreich abgeschlossener Lifecycle-Archivlauf existieren (sonst 409). Ein bloßer normaler Runtime-Stop erfüllt das nicht. Identitätskonflikte zwischen Slug und Alias ergeben 409. Metadaten mit eingebetteten Secretfeldern werden abgewiesen; bestehende sensible Metadaten werden bei Projektionen bereinigt. Diese Sicherheitsgrenzen sind keine automatische Migration des Bestands.
