# Erweiterungen

- `contracts.py`: technische Projektion, Profilrevisionen, Aliase, konfliktbewusste Metadatenpläne und Kompatibilitätsexport.
- `access.py`, `redaction.py`, `http_security.py`: bestehender Administrator-Bearer plus eingeschränkte Identitäten, explizite Browserrollen, CSRF und bereinigte Fehler.
- `runtime.py`: typisierter Docker-CLI-Adapter, registrierte Compose-Zuordnung, Beobachtungen und Diagnose. Keine Shell-Pipelines.
- `operations.py`: persistente Pläne, Queue, Zustimmung, Idempotenz, Dateisperren, Serialisierung und Unterbrechungsbehandlung.
- `policies.py`: feste Basisprüfungen und unveränderliche servicebezogene Regelversionen mit typisierten Aktionen.
- `routing.py`, `caddy_apply.py`: Header/TLS/Wildcards, manuelle Ownership, vollständige Kandidatenvalidierung und atomarer Routentausch mit Rückfall.
- `storage.py`: Inventur und konservative Bereinigungsvorschläge. Keine Lösch-API.
- `management_api.py`, `management_ui.py`, `static/`: additive Backendrouten und schlanke API-Oberfläche.

Lange Aktionen laufen nach HTTP 202 in einem Workerthread. Die DB hält Status und Ergebnis; ein kernelverwalteter Lock serialisiert die teuren Schritte. Es gibt keinen zusätzlichen Queue-Dienst. Nach Neustart werden verwaiste angenommene Aufträge als `interrupted` sichtbar; kein automatisches Wiederholen unsicherer Seiteneffekte.
