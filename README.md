# Control-Plane

Die Control-Plane ist die Codebasis der Docker-basierten Control Plane.

## Source und Build Area

- Source-Code: `/home/marco/selfhost/apps/services/control-plane`
- Build-Area-Job: `/home/marco/selfhost_outsourced/build_area/services/control-plane`
- Arbeitskopie: `/home/marco/selfhost_outsourced/build_area/services/control-plane/workdir`
- Entwicklungs-venv: `/home/marco/selfhost_outsourced/build_area/services/control-plane/workdir/.venv`
- Docker-Image: `selfhost/control-plane:build-area`

Der Source-Ordner bleibt bewusst schlank. Abhaengigkeiten, venv, Testlauf und Docker-Build liegen im Build-Area-Job.

## Entwicklung

```bash
cd /home/marco/selfhost_outsourced/build_area/services/control-plane
./build.sh
```

Zum Aktivieren der Entwicklungs-venv aus dem Source-Ordner:

```bash
source /home/marco/selfhost/apps/services/control-plane/activate-venv.sh
```

## Betrieb

Produktiv laeuft die Control Plane als Docker-Container `control-plane` im Foundation-Stack:

```text
/home/marco/selfhost/stacks/services/control-plane
```

Der Container bindet lokal auf `127.0.0.1:8765`; Caddy routet die Subdomains-Web-UI darueber.
