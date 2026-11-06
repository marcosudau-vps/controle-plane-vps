# Späterer Rollout

Dieser Auftrag rollt nichts produktiv aus. Vor einem späteren Rollout: PR reviewen, Backup/Restorebelege prüfen, eigene Slug-Aliase, Kernschutz und Runtime-Zuordnungen fachlich bestätigen. Vorhandene manuelle Overrides nicht löschen.

1. PostgreSQL in separater Umgebung auf 0002 migrieren und Datenparität prüfen.
2. Python 3.12 verwenden, Dependencies aus `requirements-runtime.lock` installieren; Anwendung und CLI aus diesem Repository bauen. Der Dockerfile kopiert Migrationen, Alembic-Konfiguration und UI-Assets.
3. Externes Caddy-Cloudflare-Basisimage bereitstellen. Es ist kein fremder Servicecode im Repository enthalten.
4. Kandidatenimage unter einem neuen Namen bauen; nie ungeprüft das produktive Tag überschreiben. Altes Image samt Compose/Secrets getrennt sichern.
5. In isolierter Umgebung CP_SELFHOST_ROOT, generierte Pfade, Datenbank und Lockpfade explizit setzen. Ausführung zunächst deaktiviert lassen. Portalrollen separat konfigurieren.
6. Nach Migrations-/API-/Caddy-/Lifecycle-Smokes einen eigenen produktiven Wartungsauftrag freigeben. Erst dann kontrollierter Image-/Konfigurationswechsel und ggf. Runtime-Ausführung.

Einschränkungen: Compose include/extends brauchen eine geprüfte flache Definition. Privilegierte Host-/Docker-Socket-Stacks werden durch Standardoperationen nicht verändert. Externe Compose-Neuerstellungen können Docker-Restart-Policies überschreiben und müssen abgeglichen werden. Kein automatischer Boot-Orchestrator oder Host-Recoverydienst wird installiert.

Ein Image-Rollback setzt gleich gebliebene Compose-Semantik voraus und stellt keine Datenbank- oder Applikationsdaten zurück. DB-/Volume-Upgrades brauchen eigene Backups und ein Service-Runbook.
