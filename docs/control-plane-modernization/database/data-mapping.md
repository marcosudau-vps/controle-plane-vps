# Datenherkunft und YAML-Abgleich

| Bisheriges Feld | Kanonische Quelle | Import/Export |
|---|---|---|
| service.slug / cp_metadata.id | bestehende Serviceidentität | Abweichung blockiert; keine Umbenennung |
| service.name | services.title | explizite Konfliktauflösung |
| profile.summary / cp_metadata.summary | services.summary | keine doppelte Profilspalte |
| profile.description | service_profiles.description | versioniertes Profil |
| service.category | service_profiles.category | versioniertes Profil |
| cp_metadata Owner/Typ/Tags/Kritikalität | services | durch ServiceUpdate validiert |
| lifecycle archivable/snapshot_supported | Profil | Konflikte melden; Kernschutz hat Vorrang |
| paths | Profil mit typisierten Pfadrollen | nur unter erlaubten Roots |
| runtime / routes / dependencies | bestehende Runtimes/Routes/Relations | separate Registry-Abgleichpunkte, kein stilles Überschreiben |
| profile components/routes Sonderfelder | nicht automatisch importiert | ausdrücklich unmapped, Original erhalten |
| operator_permissions | Hostkonfiguration/Administrationskontext | keine automatische Rechtevergabe |

`metadata/plan` meldet Kandidaten, Konflikte, unbekannte Profilfelder und Referenzsektionen. `metadata/import` verlangt denselben Hash, eine aktuelle Service-/Profilrevision und eine Entscheidung je Konflikt (`database`, `service_yaml`, `profile_yaml`). Ein unbekanntes Feld muss vor Import fachlich zugeordnet werden. Originaldateien werden nicht verändert.

`metadata/export` liefert generierte Service-/Profil-YAML-Projektionen. Bei mehreren Runtimes oder unvollständigen Pfaden wird keine Lifecycle-Kompatibilität behauptet. `contract?format=yaml` exportiert den gesamten technischen API-Vertrag. Bestehender Lifecycle liest weiterhin kompatible Manifestdateien; deren Ablösung wird erst nach vollständiger Migrationsabnahme freigeschaltet.

Die lokale Inventur fand 63 Service-/Profil-YAML-Dateien, darunter 22 Profile. Reguläre Profile enthalten schema_version/summary/description; ein Spezialprofil enthält zusätzliche Komponenten-/Routenreferenzen. Doppelte archivable-Angaben werden niemals automatisch nach Dateidatum ausgewählt.
