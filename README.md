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

Die API lauscht im Container auf Port `8765`. Der veröffentlichte Hostport hängt von
der Compose-Konfiguration ab; `CP_API_URL` für CLI/MCP explizit auf die tatsächliche
Adresse setzen. Caddy routet die Subdomain-Weboberfläche.

## Modernisierungskandidat

Version 0.2 ergänzt die bestehende Anwendung. Aktuelle Entwickler-, API-, Contract-,
Migrations- und Testreferenz: [docs/control-plane-modernization](docs/control-plane-modernization/README.md).

Die obigen historischen Betriebs-/Buildpfade beschreiben den ursprünglichen Bestand.
Für Entwicklung und Tests eine isolierte Konfiguration verwenden; keine Build-Skripte
gegen das produktive Verzeichnis aufrufen. Neue Runtimeausführung ist standardmäßig
abgeschaltet. Es wird durch dieses Repository kein Deployment oder Merge ausgelöst.
