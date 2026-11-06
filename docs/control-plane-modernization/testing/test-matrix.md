# Testmatrix

| Bereich | Nachweise | Grenze |
|---|---|---|
| Bestehende Registry/API/Ports/Subservices/UI/MCP/Lifecycle | ursprüngliche 34 Tests unverändert | keine produktiven Mutationen |
| Contract/Profil/Aliase/Import/Export | test_management | Konfliktauflösung statt automatischem YAML-Cutover |
| Runtime/Operationen/Rechte/Idempotenz | test_management, test_security_and_routing | alle Negativfälle mit Fake-Docker |
| Reale Runtime | test_runtime_live | eigenes benanntes Wegwerfprojekt; Start/Stop/Autostart/Identität |
| Builds/Deployment/Rollback | test_management | Registry-/Compose-/External-/Mixed-Adapter; tatsächliche Image-Updatefolge mit Fakebackend |
| Datenbank | test_migrations plus geschützter Dump-Proberestore | echter PG16; leeres Schema, Upgrade/Downgrade/erneutes Upgrade; vollständige Altwert-Parität |
| Caddy | test_security_and_routing | echte vollständige Validierung mit kopiertem Caddy-Cloudflare-Binary; kein Live-Reload/DNS-Apply |
| Browser | test_browser | echtes Chromium, Desktop/Mobil, bestätigter Stop, Cookies/CSRF, keine externen Requests |
| Secrets/Pfade/Archive/DB-Ausfall | test_security_and_routing | synthetische sensible Werte, unzulässige Pfade und manipulierte Backups |
| Storage | test_management | aktive, getaggte und Rollback-Images geschützt; Volumes geschützt; keine Bereinigung |
| Paket | wheel-build + Assetprüfung | externe Caddy-Basis bleibt Buildvoraussetzung |

Standard: `python -m pytest`. Optionale Integration einschalten: CP_TEST_POSTGRES_URL (127.0.0.1, DB-Präfix ctpl_test_), CP_LIVE_DOCKER_TESTS=1, CP_BROWSER_TESTS=1, CP_TEST_CADDY_BINARY=/absoluter/testpfad/caddy. Ein dedizierter Docker-Testdaemon oder explizit freigegebener lokaler Testdaemon ist Voraussetzung; die Tests übernehmen kein vorhandenes gleichnamiges Projekt.

Browser braucht Playwright/Chromium und passende Systembibliotheken. Im Projektlauf wurden fehlende Bibliotheken ausschließlich lokal extrahiert, keine Hostpakete installiert. Artefaktpfad via CP_BROWSER_ARTIFACT_DIR setzen. Temporäre Dateien via TMPDIR in der Testumgebung bündeln.
