# API: policies

## Endpunkte

| Methode | Pfad | JSON-Requestschema | Parameter | dokumentierte Statuscodes | Zugang |
|---|---|---|---|---|---|
| GET | `/api/v1/activity` | – | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/comments` | CommentCreate | – | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/agent-context/{slug}` | – | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/services/{slug}/policies` | – | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| POST | `/api/v1/policies` | RuleInput | – | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| POST | `/api/v1/services/{slug}/policies/validate` | PolicyCheck | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/management/context` | – | – | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/management/activities` | – | – | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |

Request-Feldtypen, Pflichtfelder, Enums und Antworten stehen in [OpenAPI](openapi.json). Die Contractseiten beschreiben Beziehungen, Fehler und Kompatibilität. Keine hier aufgeführte Route ist nur als zukünftiger Platzhalter dokumentiert.
