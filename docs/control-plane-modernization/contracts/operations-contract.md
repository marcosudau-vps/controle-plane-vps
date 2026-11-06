# Operations-Contract

Plan: `POST /api/v1/services/{slug}/operations/plan` mit runtime_id, action und idempotency_key. Aktionen: start, stop, restart, autostart, pull, build, deploy, update, rollback. autostart braucht autostart_policy; rollback braucht release_id.

Der gespeicherte Plan bindet Service-/Profil-/Policyrevision, Compose- und Environment-Dateihashes, Containeridentitäten, Quellen und Abhängigkeiten. Laufzeit 15 Minuten. Execute verlangt plan_hash, approved=true, denselben Actor, passenden Scope und aktivierte Ausführung. Neuprüfung erfolgt bei Annahme und nach Queue-Wartezeit. Veränderte Pläne ergeben 412; blockierte oder konkurrierende Projekte 409.

Zustände: planned → queued → running → completed/failed; Neustart kann queued/running nach interrupted überführen. Ein 202 bestätigt Annahme, nicht Erfolg. Ergebnis und Eventliste sind persistent; rohe Kommandoumgebungen und unbereinigte Fehlermeldungen werden nicht gespeichert. Die Warteschlange ist standardmäßig auf 20 angenommene/laufende Aufträge begrenzt (HTTP 429 bei Überlast). Pro Actor ist ein Idempotenzschlüssel eindeutig. Identische Wiederholung liefert denselben Auftrag; eine andere Eingabe unter gleichem Schlüssel ergibt 409.

Kostenintensive Schritte werden über einen gemeinsamen kernelverwalteten Lock serialisiert. Ein Prozessabbruch löst den Lock. Vor erneuter Ausführung nach Fehler/Unterbrechung Zustand prüfen und frischen Plan erzeugen. Beispiel Execute: `{ "plan_hash":"<64 lowercase hex>", "approved":true }`.

Die folgenden Typnamen verwenden die SQLAlchemy-Darstellung; die PostgreSQL-DDL steht in `migrations/baseline.sql` und `migrations/modernization.sql`. Insbesondere entspricht DATETIME einem PostgreSQL-Timestamp.

## Persistierte Felder

### `operation_runs`

| Feld | Datentyp | Pflicht | Default / Beziehung |
|---|---|---|---|
| id | VARCHAR(36) | ja | Anwendung |
| service_id | VARCHAR(36) | ja | –; → services.id |
| runtime_id | VARCHAR(36) | ja | –; → runtimes.id |
| actor | VARCHAR(120) | ja | – |
| action | VARCHAR(40) | ja | – |
| status | VARCHAR(40) | ja | Anwendung |
| active_key | VARCHAR(120) | nein | – |
| idempotency_key | VARCHAR(120) | ja | – |
| plan_hash | VARCHAR(64) | ja | – |
| plan | JSON | ja | – |
| result | JSON | ja | Anwendung |
| events | JSON | ja | Anwendung |
| error | TEXT | ja | Anwendung |
| expires_at | DATETIME | ja | – |
| created_at | DATETIME | ja | Anwendung |
| updated_at | DATETIME | ja | Anwendung |
