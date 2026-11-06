---
title: selfhostctl
description: selfhostctl ist die CLI fuer Menschen und Agents. Sie spricht mit der Docker-Control-API
  auf http://127.0.0.1:8765.
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

# selfhostctl

`selfhostctl` ist die CLI fuer Menschen und Agents. Sie spricht mit der Docker-Control-API auf `http://127.0.0.1:8765`.

## Betrieb

- API-Ziel: `http://127.0.0.1:8765`
- Control-API-Container: `control-api`
- Source der CLI: Bestandteil von `/home/marco/selfhost/apps/services/control-plane`
- Entwicklungsumgebung: Build-Area-Job `control-plane`
- Aktiver CLI-Pfad: `/home/marco/selfhost_outsourced/build_area/services/control-plane/workdir/.venv/bin/selfhostctl`
- Bequemer Alias: `/home/marco/selfhost/tools/selfhostctl`

## Standardbefehle

```bash
/home/marco/selfhost/tools/selfhostctl doctor
/home/marco/selfhost/tools/selfhostctl validate --scope all
/home/marco/selfhost/tools/selfhostctl service list
```

Service-spezifische Healthchecks werden mit der Option `--service-slug` ausgefuehrt:

```bash
/home/marco/selfhost/tools/selfhostctl healthchecks-run --service-slug dozzle
```

## Regeln

- Agents verwenden `selfhostctl` oder direkt die API.
- Generierte Caddy-Dateien werden nicht manuell editiert.
- Vor Apply-Schritten wird validiert.
