# API: deployments

## Endpunkte

| Methode | Pfad | JSON-Requestschema | Parameter | dokumentierte Statuscodes | Zugang |
|---|---|---|---|---|---|
| GET | `/api/v1/services/{slug}/deployments/sources` | – | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| PUT | `/api/v1/services/{slug}/deployments/sources` | SourceInput | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/services/{slug}/deployments/releases` | – | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/services/{slug}/deployments/images` | – | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |

Request-Feldtypen, Pflichtfelder, Enums und Antworten stehen in [OpenAPI](openapi.json). Die Contractseiten beschreiben Beziehungen, Fehler und Kompatibilität. Keine hier aufgeführte Route ist nur als zukünftiger Platzhalter dokumentiert.
