---
title: Generierte Control-Plane-Artefakte
description: Wenn ein generiertes Artefakt falsch ist, wird die Quelle oder der Generator korrigiert.
  Die generierte Datei selbst ist nicht der Pflegeort.
page_type: reference
section: services
service: control-plane
status: active
service_status: active
tags:
- services
- reference
- control-plane
- service
- api
- mcp
service_registered: '2026-05-25'
service_metadata_updated: '2026-07-01'
generated: false
---

# Generierte Control-Plane-Artefakte

Die fruehere globale Ablage fuer generierte Artefakte wird nicht mehr verwendet. Generierte Artefakte liegen servicebezogen unter der Control Plane:

```text
/home/marco/selfhost/data/services/control-plane/generated/caddy
```

Aktuelle Dateien:

| Datei | Zweck |
|---|---|
| `routes.caddy` | von der Control Plane erzeugte Service-Routen |
| `auto_cert_zones.caddy` | von Auto-Cert-Zones erzeugte TLS-Zonen |

Der Docker-Caddy bindet diesen Ordner nach `/etc/caddy/generated` ein.

## Regel

Wenn ein generiertes Artefakt falsch ist, wird die Quelle oder der Generator korrigiert. Die generierte Datei selbst ist nicht der Pflegeort.
