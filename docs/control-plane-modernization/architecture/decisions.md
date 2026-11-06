# Entscheidungen für diesen Kandidaten

1. Bestehender Quellcode, IDs und Endpunkte haben Vorrang vor historischen Modulskizzen. Erweiterungen sind additiv.
2. PostgreSQL bekommt eine explizite Alembic-Baseline und Revision 0002. PostgreSQL-Startup prüft die Revision und führt keine implizite DDL aus. SQLite bleibt isolierter Test-/Entwicklungsbootstrap.
3. Profile enthalten nur fehlende Metadaten. Titel, Summary, Owner und Tags bleiben in `services`. Eine Aliaszeile benennt keine Verzeichnisse um.
4. `OperationRun` erhält einen eigenen Lebenszyklus; `LifecycleRun` bleibt Archiv-/Restore-Historie. Keine Wiederverwendung inkompatibler Zustandswerte.
5. Standardstart nutzt `compose start`, kein Pull/Build. Updates unterscheiden Registry-, Compose- und registrierte externe Quellen je Compose-Service.
6. Rollback pinnt vorherige Image-IDs. Bei geänderter Compose-Semantik wird ein reines Image-Rollback blockiert; Datenbank-/Datendowngrades werden nicht behauptet.
7. Autostart wird tatsächlich über Docker-Restart-Policies geändert. Bei Neuerstellung setzt der Controller diese Policy erneut. Bestehende Compose-Dateien werden nicht automatisch umgeschrieben; externer Compose-Aufruf kann weiterhin Drift erzeugen.
8. Kernservices, Datenbanken, harte Abhängigkeiten, fremde Pfade, privilegierte Container und Docker-Socket-Mounts sind geschützt. Solche Sonderwartung wird nicht durch einen unkontrollierten API-Schalter freigeschaltet.
9. Alle neuen ausführenden Pläne benötigen Zustimmung und passende Scopes. Der vorhandene Adminkey bleibt kompatibel; fehlender Schlüssel öffnet die API nicht mehr.
10. Bestehende manuelle Caddy-Overrides bleiben Dateien. Ownership wird registriert; eine aktive generierte Überschneidung blockiert die Erzeugung. Der Legacy-Overridepfad bleibt als Kompatibilitätsquelle lesbar.
11. Keine generische Shell, kein Host-Supervisor, keine Änderung bestehender Agentenrechte, keine Docs-Plattform, kein produktiver Rollout.
