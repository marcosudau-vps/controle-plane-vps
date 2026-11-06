# Schemaänderungen

0001 ist die eingefrorene ursprüngliche Struktur mit 20 Tabellen. 0002 fügt sieben Tabellen sowie `runtimes.desired_state` und `runtimes.autostart_policy` hinzu. Keine bestehenden IDs oder Beziehungen werden umgeschlüsselt. Alte Runtime-Zeilen erhalten `manual` und `on_demand`; das verändert keine Docker-Policy.

Neue Tabellen: `service_profiles` (1:1 Service), `service_aliases`, `deployment_sources` (Runtime/Compose-Service eindeutig), `operation_runs` (Actor/Idempotenzschlüssel eindeutig, aktive Projektbelegung eindeutig), `deployment_releases`, `policy_rules` (Regel-ID/Version eindeutig, Version positiv) und `route_options` (1:1 Route). Fremdschlüssel sowie Check-Constraints sind in `migrations/modernization.sql` eingefroren.

Profile besitzen eine anwendungsseitige compare-and-set Revision. Operative Identität wird durch Slug-/Alias-Konfliktprüfung unter gemeinsamem Dateilock geschützt. Policies sind append-only; eine bestehende Regelversion wird nicht überschrieben. Laufhistorien verhindern ein versehentliches Löschen referenzierter Services.
