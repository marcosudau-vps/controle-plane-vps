# API: README

Die aktuelle [OpenAPI-Datei](openapi.json) wird aus `app.openapi()` erzeugt. HTTP-Antworten verwenden in der Bestands-API das Envelope `{ok,data,error}`; Validierungsfehler enthalten bereinigte detail-Einträge. Neue HTTP-Fehler liefern außerdem einen stabilen Code (UNAUTHENTICATED, PERMISSION_DENIED, NOT_FOUND, STATE_CONFLICT, STALE_PLAN, VALIDATION_FAILED, BACKEND_UNAVAILABLE) und X-Request-ID. Das gleiche Headerfeld korreliert erfolgreiche Antworten.

Neue lesende Endpunkte benötigen read und einen passenden Slugscope. Runtimeaktionen brauchen runtime, Pull/Build/Deployment/Rollback deploy, Profil/Alias/Quellen/Ownership configure, Regeländerungen policy. Globale Inventuren erfordern globalen Servicescope. Historische Verwaltungsendpunkte verwenden weiterhin ausschließlich den Adminkey. Browser-Schreibzugriffe benötigen zusätzlich Same-Origin und X-CP-CSRF.

200 bedeutet erfolgreiche synchrone Verarbeitung, 202 nur angenommene Operation. Fehler: 401 Auth, 403 Rechte/Schutz/Zustimmung, 404 unbekannt, 409 Konflikt/Blockade, 412 veralteter Plan/Revision, 422 Schema/Pfad, 503 Backend. Routen können zusätzliche historische Statuscodes verwenden; OpenAPI und Quellcode sind maßgeblich.

## Endpunkte

| Methode | Pfad | JSON-Requestschema | Parameter | dokumentierte Statuscodes | Zugang |
|---|---|---|---|---|---|
| GET | `/health` | – | – | 200 | Bestands-Login / Health |
| POST | `/api/v1/db/init` | – | – | 200, 422 | Adminkey (Bestands-API) |
| GET | `/subdomains` | – | – | 200 | Bestands-Login / Health |
| POST | `/api/v1/resources` | ResourceCreate | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/apis` | ApiEntityCreate | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/skills` | SkillCreate | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/secret-refs` | SecretRefCreate | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/docs` | DocCreate | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/healthchecks` | HealthcheckCreate | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/healthchecks/run` | – | service_slug (query) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/validate` | – | scope (query) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/generate/all` | – | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/export/json` | – | – | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/meta` | – | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/docker/storage/cleanup/plan` | – | – | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/docker/storage` | – | – | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |

Request-Feldtypen, Pflichtfelder, Enums und Antworten stehen in [OpenAPI](openapi.json). Die Contractseiten beschreiben Beziehungen, Fehler und Kompatibilität. Keine hier aufgeführte Route ist nur als zukünftiger Platzhalter dokumentiert.
