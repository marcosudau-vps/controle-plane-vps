# Migration und Restore

Nur nach Backup und separatem Proberestore arbeiten. Ein existierendes Schema niemals blind mit `stamp` als kompatibel deklarieren.

```bash
# In einer isolierten Kopie; CP_DATABASE_URL und CP_DB_SCHEMA zuvor explizit setzen.
python -m control_plane.migration_tools
python -m alembic stamp 0001
python -m alembic upgrade head
```

`migration_tools` vergleicht alle ursprünglichen Spalten und PostgreSQL-Typen mit der eingefrorenen Signatur. Zusätzlich Tabellen, Constraints und Backupergebnisse reviewen. Der Testlauf hat den produktiven Custom-Dump in einen separaten PostgreSQL-16-Container restauriert, die Baseline geprüft, auf 0002 migriert und sämtliche ursprünglichen Werte aller 20 Tabellen verglichen: gleich.

Für eine leere PostgreSQL-Datenbank: `python -m alembic upgrade head`. Schema muss ein einfacher Identifier aus Kleinbuchstaben/Ziffern/Unterstrichen sein. Migrationen sind PostgreSQL-spezifisch; SQLite-Tests verwenden den vorhandenen ORM-Bootstrap.

`init_db` erlaubt PostgreSQL-Schreibbetrieb erst bei Revision 0002. Falscher Versionsstand beendet den Anwendungsstart mit Migrationsdiagnose. Die alte `/db/init`-Route führt dort keine DDL mehr aus.

`downgrade 0001` entfernt die neuen Verwaltungsdaten und ist nur im Wegwerftest ausgeführt worden. Es stellt keinen verlustfreien produktiven Rückweg dar. Nach Einführung neuer Daten vorherigen DB-Snapshot restaurieren und mit vorherigem Image kombinieren. Downgrade unter die Baseline ist bewusst gesperrt.
