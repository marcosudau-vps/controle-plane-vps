# API: runtime

Plan-/Execute-/Status-Details: [Operations-Contract](../contracts/operations-contract.md). Betrieb und Registry-Lifecycle bleiben getrennt. Ein Backendausfall verhindert nicht den Katalogabruf.

## Endpunkte

| Methode | Pfad | JSON-Requestschema | Parameter | dokumentierte Statuscodes | Zugang |
|---|---|---|---|---|---|
| POST | `/api/v1/runtimes` | RuntimeCreate | – | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/registry/reconcile` | – | – | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/services/{slug}/runtime/status` | – | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/services/{slug}/runtime/logs` | – | slug (path), runtime_id (query), tail (query) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| POST | `/api/v1/services/{slug}/operations/plan` | OperationInput | slug (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| POST | `/api/v1/operations/{operation_id}/execute` | ExecuteInput | operation_id (path) | 202, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/operations` | – | limit (query) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/operations/{operation_id}` | – | operation_id (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/management/system` | – | – | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |

Request-Feldtypen, Pflichtfelder, Enums und Antworten stehen in [OpenAPI](openapi.json). Die Contractseiten beschreiben Beziehungen, Fehler und Kompatibilität. Keine hier aufgeführte Route ist nur als zukünftiger Platzhalter dokumentiert.

## Abgleich und Antworten

`registry/reconcile` ist lesend und liefert `applied:false` und `findings` mit Code, Slug/Projekt und Korrekturhinweis. Ein Alias wird auf den kanonischen Service aufgelöst; ein vorhandener Aliasstack ohne Runtime bleibt als `runtime.missing` sichtbar. `stack.unregistered` erfordert eine bewusste Registrierung. Der Aufruf registriert und verändert keine Stacks.

Runtime-Status liefert ein Envelope mit einer Liste von `RuntimeObservation`; Logs liefern begrenzte und bereinigte Zeilen. Die Operationsliste und der einzelne Auftrag liefern persistierte `OperationOut`-Objekte. System-/Storage-Inventuren verlangen globalen Servicescope. `POST .../operations/plan` liefert den gespeicherten Auftrag mit `plan`, `plan_hash` und Ablaufzeit; `execute` antwortet mit HTTP 202 und demselben Auftrag, dessen Status anschließend abgefragt wird. Auch die begrenzte Warteschlange kann bei Erreichen von 20 angenommenen/laufenden Aufträgen HTTP 429 liefern.
