# Deployment-Contract

Eine Quelle gehört zu einer Runtime und einem Compose-Service. Herkunft: registry_image, compose_build oder external_build. Ein gemischter Stack besitzt mehrere entsprechend klassifizierte Quellen; er bekommt keinen irreführenden universellen Build-Typ.

Registrierte Image-Referenz muss dem Compose-Service entsprechen. Compose-Build verlangt build:-Konfiguration. Externes Build verlangt eine serverseitig konfigurierte Workflow-ID mit festem argv/cwd. API-Eingaben sind keine Shellbefehle.

Pull/Build bereiten Artefakte vor und protokollieren ihre Image-IDs in der Operation. Deploy nutzt lokale Images. Update bereitet jede Quelle gemäß Herkunft vor und recreatet mit festgehaltenen Image-IDs, `--no-build --pull never --no-deps`. Status, Health und tatsächlich verwendete Images werden verifiziert. Releasezeilen speichern vorherige Images bereits vor dem Recreate, sodass auch ein fehlgeschlagenes Deployment diagnostizierbar bleibt.

Rollback referenziert eine Release-ID derselben Runtime. Fehlende Images, andere Runtime, geänderte Compose-Semantik und unerfüllte Abhängigkeiten blockieren. Datenbank-/Dateiformate werden nicht zurückmigriert. Beispiel Quelle: `{ "runtime_id":"<uuid>", "compose_service":"app", "source_kind":"registry_image", "image_ref":"example/app:1.0" }`.

Die folgenden Typnamen verwenden die SQLAlchemy-Darstellung; die PostgreSQL-DDL steht in `migrations/baseline.sql` und `migrations/modernization.sql`. Insbesondere entspricht DATETIME einem PostgreSQL-Timestamp.

## Persistierte Felder

### `deployment_sources`

| Feld | Datentyp | Pflicht | Default / Beziehung |
|---|---|---|---|
| id | VARCHAR(36) | ja | Anwendung |
| runtime_id | VARCHAR(36) | ja | –; → runtimes.id |
| compose_service | VARCHAR(120) | ja | – |
| source_kind | VARCHAR(40) | ja | – |
| image_ref | VARCHAR(255) | ja | – |
| workflow_id | VARCHAR(80) | ja | Anwendung |
| created_at | DATETIME | ja | Anwendung |
| updated_at | DATETIME | ja | Anwendung |

### `deployment_releases`

| Feld | Datentyp | Pflicht | Default / Beziehung |
|---|---|---|---|
| id | VARCHAR(36) | ja | Anwendung |
| operation_id | VARCHAR(36) | ja | –; → operation_runs.id |
| runtime_id | VARCHAR(36) | ja | –; → runtimes.id |
| previous_images | JSON | ja | – |
| images | JSON | ja | Anwendung |
| compose_checksum | VARCHAR(64) | ja | – |
| status | VARCHAR(40) | ja | Anwendung |
| created_at | DATETIME | ja | Anwendung |
| updated_at | DATETIME | ja | Anwendung |
