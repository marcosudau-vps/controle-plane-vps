# Bestehende Architektur

`control_plane/api.py` ist weiterhin die FastAPI-Anwendung. SQLAlchemy-Modelle und PostgreSQL bilden die Registry. `service.py`, `subservice.py`, `domains.py` und `port_allocator.py` behalten ihre Aufgaben und Identitäten. Die bisherigen CRUD-Routen, Namespace-Route mit `caddy_schutz`, Zertifikatszonen und Lifecycle-APIs bestehen weiter.

Der produktive Docker-Build referenziert eine separate Build-Area-Arbeitskopie. Vor Import wurde deren Code gegen Source und anschließend gegen `/app/control_plane` im laufenden Image verglichen: identisch. Die ursprünglichen 20 Tabellen bleiben erhalten. Der Import enthält keine Produktionsdaten oder Secrets. Historische Projektdokumentation unter `docs/existing` ist als Bestandsdokumentation zu lesen; Pfade/Ports dort sind keine neue Deploymentanweisung.

Die bestehende CLI spricht HTTP. Historische MCP-Tools behalten ihren lokalen, privilegierten DB-Zugang; neue Managementtools verwenden denselben API-Vertrag wie die CLI. Der lokale MCP-Prozess ist deshalb weiterhin ein vertrauenswürdiger administrativer Client und kein Ersatz für API-Scopes. Docker-/Unix-Rechte werden nicht verändert.

Der Dockerfile benötigt das separat erstellte Caddy-Cloudflare-Image. Es wird keine zweite Caddy-/ACME- oder Dokumentationsplattform eingeführt.
