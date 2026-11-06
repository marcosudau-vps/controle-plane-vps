# Control Plane 0.2 – technische Referenz

Dieser Stand erweitert die vorhandene FastAPI-Anwendung. Es existieren weiterhin eine Registry und ein Backend. Ausgangsstand: `82e939fdaece8cfee97edd16030a2774545a6884` (maßgeblich ist `git rev-parse main`; die Kurzkennung ist 82e939f). Die Implementierung liegt auf `feat/control-plane-completion`.

Einstieg: [Architektur](architecture/existing-architecture.md), [Entscheidungen](architecture/decisions.md), [Migrationsverfahren](database/migrations.md), [API](api/README.md), [Konfiguration](operations/configuration.md), [Testmatrix](testing/test-matrix.md), [Testergebnisse](testing/test-results.md).

Der PR ist ein isoliert geprüfter Entwicklungskandidat. In diesem Auftrag wurden keine produktiven Dateien, Datenbanken, Routen oder Container ersetzt. Die eigenständige Dokumentationsplattform und ein automatischer Rollout sind ausgeschlossen.

Technische Serviceinformationen kommen aus bestehenden Registry-Tabellen und ergänzenden Profilen. YAML bleibt lesbar und wird nicht entfernt. Importpläne verlangen explizite Konfliktauflösung; Referenzsektionen werden separat abgeglichen. Unbekannte Profilfelder werden gemeldet und nicht verworfen.

Das bestehende `/subdomains` bleibt erreichbar. `/management` ergänzt Servicekatalog, Ist-/Sollstatus, Metriken, Operationen, Autostart, Image-Herkunft, Releases, Regeln, Speicherplanung und Audit. Anmeldung verwendet vorhandene Caddy-Schutz-Cookies mit expliziten Portalrollen. Es wird kein globaler Verwaltungstoken an den Browser ausgegeben.
