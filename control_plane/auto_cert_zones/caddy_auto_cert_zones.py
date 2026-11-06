#!/usr/bin/env python3
"""
auto_caddy_cert_zones.py

Erzeugt verwaltete Caddy-Wildcard-Zonen fuer Caddy + Cloudflare DNS-01.

Ziel:
- Cloudflare-Zonen ueber den Token abrufen.
- Passende Root-Zone automatisch aus der Ziel-Domain ableiten.
- Fehlende Zertifikats-Zonen fuer tiefe Domain-Ketten berechnen.
- State-Datei und generiertes Caddyfile deterministisch schreiben.
- Optional Caddy einmal validieren und einmal reloaden.

Keine externen Python-Abhaengigkeiten.

Beispiel:
  export CLOUDFLARE_TOKEN_DNS_EDIT='...'
  export LOG_FILE='/logs/results_auto_certification_script.log'

  python3 auto_caddy_cert_zones.py \
    --domain subdomain.admin.api.service.marcosudau.com

  python3 auto_caddy_cert_zones.py \
    --domain subdomain.admin.api.service.marcosudau.com \
    --apply
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CLOUDFLARE_ZONES_URL = "https://api.cloudflare.com/client/v4/zones"
ENV_TOKEN = "CLOUDFLARE_TOKEN_DNS_EDIT"
ENV_LOG_FILE = "LOG_FILE"
ENV_LOG_FILE_COMPAT = "ENV_LOG_FILE"
STATE_VERSION = 1

DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class CloudflareZone:
    id: str
    name: str
    status: str | None = None
    permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanResult:
    target_domain: str
    root_zone: str
    requested_zones: list[str]
    existing_zones: list[str]
    new_zones: list[str]
    total_after_apply: int


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def normalize_domain(domain: str) -> str:
    value = domain.strip().lower().rstrip(".")
    if value.startswith("https://") or value.startswith("http://"):
        raise ValueError("Bitte nur einen Hostnamen uebergeben, keine URL mit http:// oder https://.")
    if "/" in value or ":" in value:
        raise ValueError("Bitte nur einen Hostnamen uebergeben, ohne Pfad oder Port.")
    return value


def validate_domain(domain: str) -> str:
    value = normalize_domain(domain)
    if not value:
        raise ValueError("Domain darf nicht leer sein.")
    if value.startswith("*."):
        raise ValueError("Bitte keinen Wildcard-Host uebergeben. Das Skript erzeugt Wildcards selbst.")
    labels = value.split(".")
    if len(labels) < 2:
        raise ValueError(f"Ungueltige Domain: {domain!r}")
    for label in labels:
        if not DOMAIN_LABEL_RE.match(label):
            raise ValueError(f"Ungueltiges DNS-Label {label!r} in Domain {domain!r}")
    return value


def get_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment-Variable {name} ist erforderlich.")
    return value


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise RuntimeError(f"Env-Datei nicht gefunden: {path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def apply_env_file(path: Path) -> None:
    values = load_env_file(path)
    for key, value in values.items():
        os.environ.setdefault(key, value)
    if os.environ.get(ENV_LOG_FILE_COMPAT) and not os.environ.get(ENV_LOG_FILE):
        os.environ[ENV_LOG_FILE] = os.environ[ENV_LOG_FILE_COMPAT]


def log_event(log_file: str | None, **fields: Any) -> None:
    if not log_file:
        return
    payload = {
        "ts": utc_now_iso(),
        **fields,
    }
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def cloudflare_api_get_zones(token: str, timeout_seconds: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        CLOUDFLARE_ZONES_URL,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "auto-caddy-cert-zones/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Cloudflare API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cloudflare API nicht erreichbar: {exc}") from exc


def parse_cloudflare_zones(response_json: dict[str, Any]) -> list[CloudflareZone]:
    if not response_json.get("success"):
        raise RuntimeError(f"Cloudflare API meldet Fehler: {response_json.get('errors')}")

    zones: list[CloudflareZone] = []
    for item in response_json.get("result", []):
        name = item.get("name")
        zone_id = item.get("id")
        if not name or not zone_id:
            continue
        permissions = tuple(str(p) for p in item.get("permissions", []) if p)
        zones.append(
            CloudflareZone(
                id=str(zone_id),
                name=validate_domain(str(name)),
                status=item.get("status"),
                permissions=permissions,
            )
        )
    return sorted(zones, key=lambda z: z.name.count("."), reverse=True)


def ensure_dns_edit_permission(zone: CloudflareZone) -> None:
    required = {"#zone:read", "#dns_records:edit"}
    available = set(zone.permissions)
    missing = sorted(required - available)
    if missing:
        raise RuntimeError(
            f"Cloudflare-Zone {zone.name!r} gefunden, aber dem Token fehlen Rechte: {', '.join(missing)}"
        )


def find_best_matching_cloudflare_zone(target_domain: str, zones: list[CloudflareZone]) -> CloudflareZone:
    target = validate_domain(target_domain)
    matches = [z for z in zones if target == z.name or target.endswith("." + z.name)]
    if not matches:
        known = ", ".join(z.name for z in zones) or "keine"
        raise RuntimeError(
            f"Keine Cloudflare-Zone passt zu {target!r}. Bekannte Zonen: {known}"
        )
    return max(matches, key=lambda z: len(z.name))


def derive_certificate_zones(target_domain: str, root_zone: str, include_root_zone: bool = True) -> list[str]:
    """
    Leitet die verwalteten Zertifikats-Zonen ab.

    Beispiel:
      target_domain = subdomain.admin.api.service.domain.com
      root_zone     = domain.com

    Ergebnis mit include_root_zone=True:
      domain.com
      service.domain.com
      api.service.domain.com
      admin.api.service.domain.com

    Die volle Ziel-Domain wird nicht als eigene Zone aufgenommen, weil sie bereits
    durch *.admin.api.service.domain.com abgedeckt wird.
    """
    target = validate_domain(target_domain)
    root = validate_domain(root_zone)

    if target != root and not target.endswith("." + root):
        raise ValueError(f"{target!r} liegt nicht unter Root-Zone {root!r}")

    root_labels = root.split(".")
    target_labels = target.split(".")
    extra_labels = target_labels[: len(target_labels) - len(root_labels)]

    zones: list[str] = []
    if include_root_zone:
        zones.append(root)

    # Fuer foo.bar.domain.com entstehen:
    #   domain.com
    #   bar.domain.com
    # Nicht: foo.bar.domain.com, weil das der konkrete Leaf-Host ist.
    for i in range(len(extra_labels) - 1, 0, -1):
        zones.append(".".join(extra_labels[i:] + root_labels))

    return dedupe_preserve_order(zones)


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": STATE_VERSION, "roots": {}}
    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    if not isinstance(state, dict):
        raise ValueError("State-Datei ist kein JSON-Objekt.")
    state.setdefault("version", STATE_VERSION)
    state.setdefault("roots", {})
    return state


def get_managed_zones_for_root(state: dict[str, Any], root_zone: str) -> list[str]:
    root_obj = state.get("roots", {}).get(root_zone, {})
    zones = root_obj.get("zones", [])
    return sorted({validate_domain(str(z)) for z in zones}, key=zone_sort_key)


def zone_sort_key(zone: str) -> tuple[int, str]:
    return (zone.count("."), zone)


def plan_certificate_zones(
    target_domain: str,
    root_zone: str,
    state: dict[str, Any],
    include_root_zone: bool,
) -> PlanResult:
    requested = derive_certificate_zones(target_domain, root_zone, include_root_zone=include_root_zone)
    existing = get_managed_zones_for_root(state, root_zone)
    existing_set = set(existing)
    new_zones = [z for z in requested if z not in existing_set]
    total_after_apply = len(set(existing) | set(new_zones))
    return PlanResult(
        target_domain=target_domain,
        root_zone=root_zone,
        requested_zones=requested,
        existing_zones=existing,
        new_zones=new_zones,
        total_after_apply=total_after_apply,
    )


def enforce_limits(plan: PlanResult, max_new_zones_per_run: int, max_total_zones_per_root: int) -> None:
    if len(plan.new_zones) > max_new_zones_per_run:
        raise RuntimeError(
            f"Abbruch: {len(plan.new_zones)} neue Zonen waeren noetig, "
            f"Limit ist {max_new_zones_per_run}. Neue Zonen: {', '.join(plan.new_zones)}"
        )
    if plan.total_after_apply > max_total_zones_per_root:
        raise RuntimeError(
            f"Abbruch: Root-Zone {plan.root_zone!r} haette danach {plan.total_after_apply} "
            f"verwaltete Zonen, Limit ist {max_total_zones_per_root}."
        )


def apply_plan_to_state(state: dict[str, Any], plan: PlanResult) -> dict[str, Any]:
    roots = state.setdefault("roots", {})
    root_obj = roots.setdefault(plan.root_zone, {})
    current = set(str(z) for z in root_obj.get("zones", []))
    current.update(plan.new_zones)
    root_obj["zones"] = sorted(current, key=zone_sort_key)
    root_obj["updated_at"] = utc_now_iso()
    state["version"] = STATE_VERSION
    state["updated_at"] = utc_now_iso()
    return state


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    path.chmod(0o644)


def render_caddyfile_from_state(state: dict[str, Any]) -> str:
    all_zones: list[str] = []
    for root_zone, root_obj in sorted(state.get("roots", {}).items()):
        for zone in root_obj.get("zones", []):
            all_zones.append(validate_domain(str(zone)))

    all_zones = sorted(set(all_zones), key=zone_sort_key)

    lines: list[str] = [
        "# -----------------------------------------------------------------------------",
        "# AUTO-GENERATED FILE - DO NOT EDIT MANUALLY",
        "# Generated by auto_caddy_cert_zones.py",
        "# Purpose: managed Apex + Wildcard certificate zones for DNS-01 via Cloudflare.",
        "# -----------------------------------------------------------------------------",
        "",
    ]

    root_zones = {validate_domain(str(root_zone)) for root_zone in state.get("roots", {})}

    for zone in all_zones:
        site_address = f"{zone}, *.{zone}" if zone in root_zones else f"*.{zone}"
        lines.extend(
            [
                f"{site_address} {{",
                "\ttls {",
                f"\t\tdns cloudflare {{env.{ENV_TOKEN}}}",
                "\t}",
                "",
                "\thandle {",
                "\t\tabort",
                "\t}",
                "}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    path.chmod(0o644)


def run_command(command: list[str], timeout_seconds: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )


def caddy_validate(args: argparse.Namespace) -> subprocess.CompletedProcess[str]:
    if args.caddy_mode == "docker":
        return run_command(
            ["docker", "exec", args.caddy_container, "caddy", "validate", "--config", args.caddy_config_in_container],
            timeout_seconds=60,
        )
    return run_command(["caddy", "validate", "--config", args.caddy_config], timeout_seconds=60)


def caddy_reload(args: argparse.Namespace) -> subprocess.CompletedProcess[str]:
    if args.caddy_mode == "docker":
        return run_command(
            ["docker", "exec", args.caddy_container, "caddy", "reload", "--config", args.caddy_config_in_container],
            timeout_seconds=60,
        )
    return run_command(["sudo", "-n", args.caddy_apply_command], timeout_seconds=60)


def print_plan(plan: PlanResult, apply: bool, no_reload: bool, generated_caddyfile: Path, state_file: Path) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"Modus: {mode}")
    print(f"Ziel-Domain: {plan.target_domain}")
    print(f"Cloudflare Root-Zone: {plan.root_zone}")
    print(f"State-Datei: {state_file}")
    print(f"Generiertes Caddyfile: {generated_caddyfile}")
    print("")
    print("Angeforderte Zertifikats-Zonen:")
    for zone in plan.requested_zones:
        print(f"  - {zone}, *.{zone}")
    print("")
    if plan.new_zones:
        print("Neue Zonen:")
        for zone in plan.new_zones:
            print(f"  - {zone}, *.{zone}")
    else:
        print("Neue Zonen: keine")
    print("")
    print(f"Gesamtzahl verwalteter Zonen nach Apply: {plan.total_after_apply}")
    if apply and no_reload:
        print("Hinweis: --no-reload aktiv, es wird nur geschrieben, nicht validiert/reloaded.")
    if not apply:
        print("Hinweis: Ohne --apply werden keine Dateien geschrieben und Caddy wird nicht neu geladen.")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Automatischer Caddy-Wildcard-Zonen-Generator fuer Cloudflare DNS-01."
    )
    parser.add_argument("--domain", required=True, help="Ziel-Host, z.B. sub.admin.api.service.domain.com")
    parser.add_argument("--state-file", default="./managed_certificate_zones.json")
    parser.add_argument("--generated-caddyfile", default="./generated/auto_cert_zones.caddy")
    parser.add_argument("--max-new-zones-per-run", type=int, default=5)
    parser.add_argument("--max-total-zones-per-root", type=int, default=30)
    parser.add_argument("--exclude-root-zone", action="store_true", help="Root-Zone nicht automatisch als zone + *.zone aufnehmen.")
    parser.add_argument("--apply", action="store_true", help="State/Caddyfile schreiben, validieren und Caddy reloaden.")
    parser.add_argument("--no-reload", action="store_true", help="Mit --apply nur Dateien schreiben, aber Caddy nicht validieren/reloaden.")
    parser.add_argument("--env-file", default="", help="Optionale Env-Datei mit CLOUDFLARE_TOKEN_DNS_EDIT und LOG_FILE.")
    parser.add_argument("--caddy-mode", choices=["local", "docker"], default="local")
    parser.add_argument("--caddy-config", default="/etc/caddy/Caddyfile")
    parser.add_argument("--caddy-apply-command", default="/usr/local/sbin/selfhost-caddy-apply")
    parser.add_argument("--caddy-container", default="caddy")
    parser.add_argument("--caddy-config-in-container", default="/etc/caddy/Caddyfile")
    parser.add_argument("--cloudflare-timeout", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    log_file = os.environ.get(ENV_LOG_FILE, "").strip() or None
    try:
        if args.env_file:
            apply_env_file(Path(args.env_file))
        log_file = os.environ.get(ENV_LOG_FILE, "").strip() or None
        token = get_required_env(ENV_TOKEN)
        target_domain = validate_domain(args.domain)
        state_file = Path(args.state_file)
        generated_caddyfile = Path(args.generated_caddyfile)

        cf_response = cloudflare_api_get_zones(token, timeout_seconds=args.cloudflare_timeout)
        zones = parse_cloudflare_zones(cf_response)
        matched_zone = find_best_matching_cloudflare_zone(target_domain, zones)
        ensure_dns_edit_permission(matched_zone)

        log_event(
            log_file,
            action="cloudflare_zones_list",
            success=True,
            target_domain=target_domain,
            root_zone=matched_zone.name,
            send_api_request=False,
            message="Cloudflare-Zonen erfolgreich abgerufen; nicht als limitrelevante DNS-API-Aktion gewertet.",
        )

        state = load_state(state_file)
        plan = plan_certificate_zones(
            target_domain=target_domain,
            root_zone=matched_zone.name,
            state=state,
            include_root_zone=not args.exclude_root_zone,
        )
        enforce_limits(plan, args.max_new_zones_per_run, args.max_total_zones_per_root)
        print_plan(plan, args.apply, args.no_reload, generated_caddyfile, state_file)

        log_event(
            log_file,
            action="plan",
            success=True,
            target_domain=target_domain,
            root_zone=plan.root_zone,
            requested_zones=plan.requested_zones,
            existing_zones=plan.existing_zones,
            new_zones=plan.new_zones,
            total_after_apply=plan.total_after_apply,
            dry_run=not args.apply,
            send_api_request=False,
            message="Plan berechnet.",
        )

        if not args.apply:
            return 0

        updated_state = apply_plan_to_state(state, plan)
        write_json_atomic(state_file, updated_state)
        write_text_atomic(generated_caddyfile, render_caddyfile_from_state(updated_state))

        log_event(
            log_file,
            action="write_files",
            success=True,
            target_domain=target_domain,
            root_zone=plan.root_zone,
            state_file=str(state_file),
            generated_caddyfile=str(generated_caddyfile),
            dry_run=False,
            send_api_request=False,
            message="State-Datei und Caddyfile geschrieben.",
        )

        if args.no_reload:
            return 0

        validate_result = caddy_validate(args)
        if validate_result.returncode != 0:
            log_event(
                log_file,
                action="caddy_validate",
                success=False,
                target_domain=target_domain,
                root_zone=plan.root_zone,
                send_api_request=False,
                stdout=validate_result.stdout,
                stderr=validate_result.stderr,
                message="Caddy-Validierung fehlgeschlagen; kein Reload ausgefuehrt.",
            )
            print(validate_result.stdout, file=sys.stdout)
            print(validate_result.stderr, file=sys.stderr)
            return validate_result.returncode

        log_event(
            log_file,
            action="caddy_validate",
            success=True,
            target_domain=target_domain,
            root_zone=plan.root_zone,
            send_api_request=False,
            stdout=validate_result.stdout,
            stderr=validate_result.stderr,
            message="Caddy-Validierung erfolgreich.",
        )

        reload_result = caddy_reload(args)
        reload_ok = reload_result.returncode == 0
        log_event(
            log_file,
            action="caddy_reload",
            success=reload_ok,
            target_domain=target_domain,
            root_zone=plan.root_zone,
            new_zones=plan.new_zones,
            send_api_request=bool(plan.new_zones),
            stdout=reload_result.stdout,
            stderr=reload_result.stderr,
            message=(
                "Caddy reload ausgefuehrt. Wenn neue Zonen vorhanden sind, startet Caddy danach die DNS-01/ACME-Vorgaenge."
                if reload_ok
                else "Caddy reload fehlgeschlagen."
            ),
        )
        print(reload_result.stdout, file=sys.stdout)
        print(reload_result.stderr, file=sys.stderr)
        return reload_result.returncode

    except Exception as exc:
        log_event(
            log_file,
            action="error",
            success=False,
            send_api_request=False,
            message=str(exc),
        )
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
