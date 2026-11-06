# Rückfallverfahren

Vor jedem späteren Rollout konsistente DB-Sicherung, alte Image-ID, Compose-Konfiguration, Quellrevision und Secret-Referenzen erfassen. Der Initialimport `main` bleibt der Vergleichsstand.

Bei Schema-/Datenfehlern neue Schreibzugriffe anhalten. Die alte Datenbank in eine separate Instanz aus dem verifizierten Custom-Dump restaurieren, Tabellen/IDs/Stichproben prüfen und mit dem alten Image testen. Danach kontrolliert umschalten. Neue Verwaltungsdaten werden durch einfaches Downgrade nicht verlustfrei erhalten.

Bei Deploymentfehlern bleibt die vorherige Image-Zuordnung in `deployment_releases.previous_images` verfügbar. Ein neuer freigegebener Rollbackplan prüft Runtime-Zuordnung, Image-Verfügbarkeit, Abhängigkeiten und Compose-Checksumme. Der Controller erzeugt eine temporäre Override-Datei mit Image-IDs, startet ohne Build/Pull und prüft Status/Health/Imageidentität. Er führt keinen impliziten Daten-Restore aus.

Caddy-Apply validiert den vollständigen Kandidaten vor dem Routentausch. Fehler restaurieren vorherige Routen-/Zonen-Dateien. Automatischer Reload bleibt ein expliziter separater Konfigurationsschalter. Nach einem Fehler aktive Konfiguration und Audit prüfen.

Unterbrochene Runtimejobs werden nicht automatisch wiederholt. Dockerzustand prüfen, einen aktuellen Plan erzeugen und ausdrücklich neu freigeben.
