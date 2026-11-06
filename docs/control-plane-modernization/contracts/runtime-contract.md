# Runtime-Contract

Eine Service-ID kann mehrere Runtimes besitzen. Standardaktionen unterstützen registrierte `docker-compose`-Runtimes. Andere Typen bleiben registrierbar und werden mit `unknown` angezeigt. Ein Compose-Projekt darf nicht mehrere Runtime-Owner besitzen.

`desired_state` ist `manual | running | stopped`; `autostart_policy` ist `on_demand | always | disabled`. Die Beobachtung ist getrennt (`running`, `stopped`, `partial`, `unhealthy`, `unknown`, `unavailable`) mit source/observed_at, Container-ID, Health, Image-ID/Referenz, Restart-Policy und CPU/RAM. Fehlender Dockerzugang führt zu unavailable, Registry-Reads bleiben möglich.

Pfade müssen registriert, absolut, traversalfrei und im eigenen Service-/Alias-Stackverzeichnis liegen. Include/extends und privilegierte Konfigurationen brauchen einen separaten Wartungsweg. Symlink-Ausbrüche und fremde Stackpfade ergeben 422.

Start ist `compose start`; Stop bewahrt Container und Volumes; Restart ist kein Recreate. Autostart ändert tatsächlich `docker update --restart` und wird verifiziert. Ein normaler Stop verändert weder Registry-Lifecycle noch Archivstatus. Beispiel: `GET .../runtime/status` liefert eine Liste typisierter `RuntimeObservation`-Objekte.

Die folgenden Typnamen verwenden die SQLAlchemy-Darstellung; die PostgreSQL-DDL steht in `migrations/baseline.sql` und `migrations/modernization.sql`. Insbesondere entspricht DATETIME einem PostgreSQL-Timestamp.

## Persistierte Felder

### `runtimes`

| Feld | Datentyp | Pflicht | Default / Beziehung |
|---|---|---|---|
| id | VARCHAR(36) | ja | Anwendung |
| service_id | VARCHAR(36) | ja | –; → services.id |
| runtime_type | VARCHAR(40) | ja | – |
| path | VARCHAR(255) | ja | Anwendung |
| compose_project | VARCHAR(120) | ja | Anwendung |
| systemd_unit | VARCHAR(120) | ja | Anwendung |
| restart_policy | VARCHAR(80) | ja | Anwendung |
| desired_state | VARCHAR(40) | ja | manual |
| autostart_policy | VARCHAR(40) | ja | on_demand |
| metadata_json | JSON | ja | Anwendung |
| created_at | DATETIME | ja | Anwendung |
| updated_at | DATETIME | ja | Anwendung |
