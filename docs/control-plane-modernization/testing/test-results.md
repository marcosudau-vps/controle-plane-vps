# Prüfergebnisse des isolierten Kandidaten

Der ursprüngliche Quellcode bestand vor der Implementierung alle 34 vorhandenen Tests. Diese Assertions blieben erhalten. Die erste Gesamtsuite bestand 66 Tests, die nachfolgenden Sicherheits-/Queueergänzungen bestanden gemeinsam 71 Tests. Der abschließende Gesamtlauf nach den Host-/Pfad- und Aliasänderungen bestand alle 73 Tests.

| Nachweis | Ergebnis |
|---|---|
| Bestand | 34 bestanden, unveränderte ursprüngliche Tests |
| Vorheriger Gesamtlauf inkl. PG, Browser, Docker, Caddy | 71 bestanden, 0 übersprungen, 403.11 Sekunden |
| Abschließende vollständige Suite | 73 bestanden, 0 fehlgeschlagen, 0 übersprungen, 484.93 Sekunden |
| Echter PostgreSQL-16-Proberestore des Ausgangsdumps, Baselineprüfung, Migration auf 0002 | alle ursprünglichen Werte/IDs in 20 Tabellen identisch |
| Migrationsregression auf leerem PG-Schema | Baseline/Upgrade/Constraints/wiederholtes Upgrade/Downgrade/Reupgrade bestanden |
| Echter Docker-Stack | eigener Wegwerfstack; Start/Stop/Autostart; Containeridentität bleibt erhalten; anschließend entfernt |
| Browser | echtes Chromium, Desktop und Mobil, Cookie-Anmeldung/CSRF, genehmigter Stop und Ergebnisanzeige, keine externen Requests |
| Caddy | vollständiger synthetischer Kandidat mit echtem Cloudflare-Caddy validiert; Pfadrouten zusätzlich per adapt auf Hostbindung geprüft |
| Provisionierung | Erfolg sowie DB-/Dateirückfall bei Fehler, unangetastete Canarydatei |
| Paket | Wheel gebaut; enthaltene Python-/UI-Dateien gegen endgültigen Quellstand geprüft |
| Image | gebaut; Image 6f253298d249; fünf HTTP-Smokes erfolgreich, 48 enthaltene Source-/Migrations-/Konfigurationsdateien bytegleich, Compose/Caddy vorhanden |
| Öffentliche Veröffentlichung | Gitleaks Arbeitsbaum und gesamte Historie: 0 Funde; zusätzlicher privater Vergleich tatsächlicher konfigurierter Produktionssecrets: 0 Treffer |
| Produktionsschutz | ursprüngliche 20 Tabellen, Source, Compose-/Buildkonfiguration und Containeridentität/Image/Startzeit unverändert |

Die geschützten Rohprotokolle, Screenshots, Restorebelege und Backups bleiben im Auftragsverzeichnis außerhalb Git. Sie enthalten keine zur Veröffentlichung erforderlichen Produktionsdaten. Das Repository enthält reproduzierbare Tests und die Konfiguration für dieselben isolierten CI-Prüfungen.

Zum Wiederholen `python -m pytest` ausführen; optionale PG-/Docker-/Browser-/Caddy-Prüfungen gemäß [Testmatrix](test-matrix.md) aktivieren. Ohne deren explizite Umgebungsvariablen meldet pytest diese Integrationen als übersprungen. Der vollständige lokale Abschlusslauf hatte diese Integrationen aktiviert. Die CI aktiviert PG, Docker und Browser; das lokal aus dem vorhandenen Build-Input kopierte Caddy-Binary wird nicht öffentlich verteilt und deshalb in CI nicht vorausgesetzt.

Build-/Pull-/Mixed-/External-/Image-Rollbackabläufe werden mit kontrolliertem Fakebackend und realistischen Image-/Composezuständen geprüft. Der reale Docker-Smoke umfasst Start/Stop/Autostart. Weder produktive Images/Volumes noch DNS wurden verändert. Ein echter Host-Reboot, produktiver Caddy-Reload, produktive Archivierung/Restore und der Rollout sind nicht Teil dieser Nachweise. Die separate Dokumentationsplattform wurde nicht implementiert.
