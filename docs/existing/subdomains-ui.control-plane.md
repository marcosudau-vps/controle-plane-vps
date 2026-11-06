---
title: Subdomains-Web-UI
description: Die Subdomains-Web-UI ist Bestandteil der Control API. Sie zeigt die registrierten Subdomains
  und zugeordneten Ports aus der Control-Plane-Datenbank.
page_type: guide
section: services
service: control-plane
status: active
service_status: active
tags:
- services
- guide
- control-plane
- service
- api
- mcp
service_registered: '2026-05-25'
service_metadata_updated: '2026-07-01'
generated: false
---

# Subdomains-Web-UI

Die Subdomains-Web-UI ist Bestandteil der Control API. Sie zeigt die registrierten Subdomains und zugeordneten Ports aus der Control-Plane-Datenbank.

## Zugriff

Oeffentliche Routen:

```text
https://subdomains.marcosudau.com/
https://subdomain.marcosudau.com/
```

Beide Routen werden ueber den manuellen Caddy-Override geroutet:

```text
/home/marco/selfhost/stacks/foundation/caddy/overrides/subdomains.caddy
```

Der Upstream ist die Docker-Control-API auf `127.0.0.1:8765`.

## Authentifizierung

Die UI ist ueber Caddy Basic Auth geschuetzt. Passwort- oder Hashwerte werden nicht in dieser Dokumentation gepflegt.
