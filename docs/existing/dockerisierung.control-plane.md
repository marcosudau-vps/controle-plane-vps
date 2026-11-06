---
title: Control Plane Dockerisierung
description: 'Damit ist der produktive Container an den Build-Area-Prozess gekoppelt: Der Source wird
  zuerst getestet und synchronisiert, danach wird das Image gebaut.'
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

# Control Plane Dockerisierung

## Zielstand

Die Control Plane laeuft nicht mehr als Host-Systemd-Service. Sie besteht aus zwei Docker-Containern im Foundation-Stack:

```text
control-plane-postgres
control-api
```

Compose-Datei:

```text
/home/marco/selfhost/stacks/foundation/control-plane/docker-compose.yml
```

## Image und Build-Kontext

`control-api` nutzt das Image:

```text
selfhost/control-api:build-area
```

Der Build-Kontext ist:

```text
/home/marco/selfhost_outsourced/build_area/control-plane/workdir
```

Damit ist der produktive Container an den Build-Area-Prozess gekoppelt: Der Source wird zuerst getestet und synchronisiert, danach wird das Image gebaut.

## Persistente Daten

```text
/home/marco/selfhost/data/services/control-plane/postgres
/home/marco/selfhost/data/services/control-plane/generated/caddy
/home/marco/selfhost/data/services/control-plane/auto-cert-zones
```

## Secrets

```text
/home/marco/selfhost/secrets/control-plane.env
/home/marco/selfhost/secrets/control-plane-postgres.env
/home/marco/selfhost/secrets/caddy.env
```

## Ports

Die API bindet lokal auf:

```text
127.0.0.1:8765
```

Dieser Host-Port ist bewusst nur lokal gebunden. Caddy laeuft mit `network_mode: host` und kann diesen Upstream deshalb direkt ueber `127.0.0.1:8765` erreichen. Andere Docker-Container sehen ihr eigenes Loopback; Healthcheck-Ziele in der Control Plane duerfen deshalb nicht blind als containeruebergreifende `127.0.0.1`-Adressen interpretiert werden.

## Verifikation

```bash
docker compose -f /home/marco/selfhost/stacks/foundation/control-plane/docker-compose.yml config -q
docker inspect -f "{{.State.Health.Status}}" control-api
curl -fsS http://127.0.0.1:8765/health
/home/marco/selfhost/tools/selfhostctl doctor
/home/marco/selfhost/tools/selfhostctl validate --scope all
```
