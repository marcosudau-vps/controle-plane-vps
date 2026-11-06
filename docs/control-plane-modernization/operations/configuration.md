# Konfiguration und Zugang

Bestehende flache YAML-Konfiguration mit CP_-Umgebungsvariablen bleibt erhalten. Legacy SELFHOST_CONTROL_-Namen bleiben unterstützt. Geheimnisse gehören in geschützte Konfiguration, nicht ins Repository. Beispiel ohne Credentials: `config.example.yaml`.

| Einstellung | Bedeutung / Default |
|---|---|
| CP_DATABASE_URL / CP_DB_SCHEMA | PostgreSQL-Verbindung und bestehendes Schema; explizit setzen |
| CP_API_URL | Tatsächlich veröffentlichte API-URL für CLI und neue MCP-Tools; nicht aus dem internen Containerport ableiten |
| CP_ENV_FILE / CP_TOKEN_FILE | bestehende geschützte CLI-Konfigurations-/Tokenreferenz |
| CP_API_TOKEN | bestehender administrativer Bearer; ohne Konfiguration keine offene Admin-API |
| CP_SCOPED_TOKENS | JSON: Token → actor, role, services; nur serverseitig |
| CP_PORTAL_ROLES | JSON: vorhandener Loginname → role, services; ohne Eintrag kein Managementzugang |
| CP_RUNTIME_APPLY_ENABLED | false; separat für spätere freigegebene Umgebung aktivieren |
| CP_OPERATIONS_DIR | lokaler gemeinsamer Lock-/Stagingpfad; Default unter Lifecycle-Archivroot |
| CP_OPERATION_TIMEOUT_SECONDS | 900 je Docker-/Buildbefehl |
| CP_MINIMUM_AVAILABLE_MEMORY_MIB | 256 für ressourcenrelevante Aktionen |
| CP_MAX_PENDING_OPERATIONS | 20 angenommene/laufende Aufträge; darüber HTTP 429 |
| CP_BUILD_WORKFLOWS | JSON: bekannte Workflow-ID → festes argv und cwd unter Build-Area-Root |
| CP_CADDY_OVERRIDE_DIR | optionaler tatsächlicher Overrideordner; sonst aktueller und Legacypfad |
| CP_CADDY_RELOAD_ENABLED | vorhandener Default false bleibt maßgeblich |

Rollen: viewer (read), operator (+runtime), deployer (+deploy), maintainer (+configure), administrator (+policy). `services` ist eine explizite Slugliste oder `["*"]`. Der alte Adminkey besitzt globalen administrativen Zugriff. Historische CRUD-/Lifecycle-Endpunkte bleiben diesem Schlüssel vorbehalten; neue Scopes eröffnen diese nicht pauschal.

Browser: bestehende HttpOnly/Secure/SameSite-Cookies plus explizite Rollenabbildung. Schreibzugriffe brauchen identischen Origin und `X-CP-CSRF: 1`. Keine Tokens in Local Storage oder HTML. Ohne Signing-Secret werden keine mit einem bekannten Development-Schlüssel signierten Cookies akzeptiert.

Beispiel für eingeschränkte Identität (Wert des Tokens ausschließlich privat konfigurieren): `{ "<private-token>": {"actor":"maintenance-agent","role":"operator","services":["example-service"]} }`.

Externe Workflows sind Administratorkonfiguration, keine Request-Argumente. Sie erhalten eine minimale Environment und keine frei gelieferten Shellparameter. Beispiel: bekannte Datei `/srv/build-area/services/example/build.py` über ein festes Python-argv starten; cwd muss im konfigurierten Build-Area-Root existieren.
