# API: lifecycle

Bestehende Manifest-/Hash-Abläufe bleiben erhalten. Archive mit Pfadausbrüchen, manipulierten Checksummen oder fremden Restorezielen werden abgewiesen. Stop ist eine separate Runtimeaktion. Archiv/Restore sind nicht produktiv ausgeführt worden.

## Endpunkte

| Methode | Pfad | JSON-Requestschema | Parameter | dokumentierte Statuscodes | Zugang |
|---|---|---|---|---|---|
| GET | `/api/v1/lifecycle/services` | – | – | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/lifecycle/services/{slug}` | – | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/lifecycle/services/{slug}/plan-snapshot` | – | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/lifecycle/services/{slug}/execute-snapshot` | LifecycleExecuteRequest | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/lifecycle/services/{slug}/plan-archive` | – | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/lifecycle/services/{slug}/execute-archive` | LifecycleExecuteRequest | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/lifecycle/archives/inspect` | LifecycleArchiveInspectRequest | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/lifecycle/archives/{archive_id}/plan-restore` | – | archive_id (path) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/lifecycle/archives/{archive_id}/execute-restore` | LifecycleExecuteRequest | archive_id (path) | 200, 422 | Adminkey (Bestands-API) |

Request-Feldtypen, Pflichtfelder, Enums und Antworten stehen in [OpenAPI](openapi.json). Die Contractseiten beschreiben Beziehungen, Fehler und Kompatibilität. Keine hier aufgeführte Route ist nur als zukünftiger Platzhalter dokumentiert.
