# Agenten-Policy-Contract

Vorhandene Skills bleiben Referenzen. Neue Verwaltungsaktionen benötigen eine Actor-Identität und Scope. Globale Basisregeln werden im Code versioniert bereitgestellt; zusätzliche Regeln sind append-only in der DB und optional servicebezogen. Je Regel-ID/Scope ist die höchste Version wirksam. Eine Regel-ID wechselt nicht stillschweigend ihren Scope.

Severity: block (verweigert passende Aktionen), requires_approval (explizite Zustimmung), warning/info (sichtbare Empfehlung). Aktionen sind enumeriert; es gibt keine frei ausführbare Validator- oder Shellsprache. Feste Basisprüfungen (Pfad, Kernschutz, Abhängigkeiten, Registry, keine impliziten Builds/Pulls) werden immer durch den Planner erzwungen.

Beispiel: `{ "rule_id":"maintenance-window", "version":1, "service_slug":"example-service", "severity":"block", "actions":["stop"], "message":"Wartungsfenster noch nicht freigegeben" }`. Erstellung verlangt administrator/policy und passenden Servicescope. Doppelte oder zurückgehende Version: 409.

GET service policies und der bestehende Agentenkontext enthalten wirksame Versionen und den technischen Contract. Die drei alten Texthinweise bleiben kompatibel, ohne veraltete Backstage-Vorgaben. Host-Docker-/sudo-Zugriff und historische lokale MCP-Schreibtools bleiben eine gesonderte privilegierte Vertrauensgrenze.

Die folgenden Typnamen verwenden die SQLAlchemy-Darstellung; die PostgreSQL-DDL steht in `migrations/baseline.sql` und `migrations/modernization.sql`. Insbesondere entspricht DATETIME einem PostgreSQL-Timestamp.

## Persistierte Felder

### `policy_rules`

| Feld | Datentyp | Pflicht | Default / Beziehung |
|---|---|---|---|
| id | VARCHAR(36) | ja | Anwendung |
| rule_id | VARCHAR(80) | ja | – |
| version | INTEGER | ja | – |
| service_id | VARCHAR(36) | nein | –; → services.id |
| severity | VARCHAR(30) | ja | – |
| actions | JSON | ja | – |
| message | TEXT | ja | – |
| owner | VARCHAR(80) | ja | – |
| created_at | DATETIME | ja | Anwendung |
| updated_at | DATETIME | ja | Anwendung |
