---
title: Auto-Cert-Zones
description: Es erzeugt Caddy-Zonen fuer Apex- und Wildcard-Zertifikate mit Cloudflare-DNS-01.
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

# Auto-Cert-Zones

Auto-Cert-Zones ist Teil der Control-Plane-Codebasis. Das Modul liegt unter:

```text
/home/marco/selfhost/apps/control-api/selfhost_control/auto_cert_zones/
```

Es erzeugt Caddy-Zonen fuer Apex- und Wildcard-Zertifikate mit Cloudflare-DNS-01. Dadurch koennen Subdomains mit mehreren Ebenen Tiefe ueber Caddy abgedeckt werden, ohne dass man fuer jede Subdomain manuell Zertifikatslogik pflegt.

## Runtime-Pfade

State:

```text
/home/marco/selfhost/data/services/control-plane/auto-cert-zones/managed_certificate_zones.json
```

Generiertes Caddyfile:

```text
/home/marco/selfhost/data/services/control-plane/generated/caddy/auto_cert_zones.caddy
```

Caddy laedt dieses Artefakt im Container ueber:

```text
/etc/caddy/generated/*.caddy
```

## Betriebliches Prinzip

- Die Quelle ist die Control Plane.
- Das generierte Caddyfile wird nicht manuell editiert.
- Cloudflare-Token liegen in `/home/marco/selfhost/secrets/caddy.env`.
