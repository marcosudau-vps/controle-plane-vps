# API: routing

Caddy-Plan rendert in staging. Apply unterstützt einen optionalen plan_hash-Queryparameter und prüft die komplette Kandidatenkonfiguration. Ohne Parameter bleibt der historische administrative Aufruf kompatibel; neue Clients sollen immer den Planhash übergeben. Bei Fehlern bleiben bzw. werden vorherige Routendateien wiederhergestellt. Der aktuelle Overridepfad wird geprüft; Legacy-Overrides bleiben lesbar. Headers und TLS-Profile sind über RouteOptionsInput typisiert.

## Endpunkte

| Methode | Pfad | JSON-Requestschema | Parameter | dokumentierte Statuscodes | Zugang |
|---|---|---|---|---|---|
| GET | `/caddy-schutz/login` | – | next (query) | 200, 422 | Bestands-Login / Health |
| POST | `/caddy-schutz/login` | – | – | 200, 422 | Bestands-Login / Health |
| GET | `/caddy-schutz/check` | – | – | 200 | Bestands-Login / Health |
| POST | `/api/v1/routes` | RouteCreate | – | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/routes` | – | – | 200, 422 | Adminkey (Bestands-API) |
| PATCH | `/api/v1/routes/{route_id}` | RouteUpdate | route_id (path) | 200, 422 | Adminkey (Bestands-API) |
| GET | `/routes-ui` | – | – | 200 | Bestands-Login / Health |
| POST | `/api/v1/ports` | PortCreate | – | 200, 422 | Adminkey (Bestands-API) |
| PATCH | `/api/v1/ports/{port_id}` | PortUpdate | port_id (path) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/generate/caddy` | – | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/deploy/caddy/plan` | – | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/deploy/caddy/apply` | – | plan_hash (query) | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/caddy/cert-zones/plan` | CaddyCertZoneRequest | – | 200, 422 | Adminkey (Bestands-API) |
| POST | `/api/v1/caddy/cert-zones/apply` | CaddyCertZoneRequest | – | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/caddy-schutz/status` | – | – | 200, 422 | Adminkey (Bestands-API) |
| PATCH | `/api/v1/caddy-schutz/services/{slug}` | CaddyProtectionUpdate | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| PATCH | `/api/v1/caddy-schutz/subservices/{slug}` | CaddyProtectionUpdate | slug (path) | 200, 422 | Adminkey (Bestands-API) |
| PATCH | `/api/v1/caddy-schutz/routes/{route_id}` | CaddyProtectionUpdate | route_id (path) | 200, 422 | Adminkey (Bestands-API) |
| GET | `/api/v1/caddy/cert-zones/status` | – | – | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| GET | `/api/v1/caddy/ownership` | – | – | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |
| PUT | `/api/v1/routes/{route_id}/options` | RouteOptionsInput | route_id (path) | 200, 401, 403, 404, 409, 412, 422, 503 | Bearer oder Portalrolle; Scope siehe unten |

Request-Feldtypen, Pflichtfelder, Enums und Antworten stehen in [OpenAPI](openapi.json). Die Contractseiten beschreiben Beziehungen, Fehler und Kompatibilität. Keine hier aufgeführte Route ist nur als zukünftiger Platzhalter dokumentiert.

## Pfade, Header und Ownership

Mehrere Pfade eines Hosts werden in einem gemeinsamen Siteblock gerendert. Die expliziten Matcher verlangen **Host und Pfad** zusammen; spezifische Pfade stehen vor dem Root-Fallback. Damit kann ein Pfad unter einem fremden Host keine Route dieses Services treffen. TLS muss für dieselbe Hostgruppe übereinstimmen. Der vorhandene Schutzhandler bleibt vor geschützten Upstreams wirksam.

`RouteOptionsInput` erlaubt `host_aliases` (bis 30), `upstream_headers`, `response_headers`, `tls_profile` (`default`, `cloudflare_dns01`), `owner_kind` (`generated`, `manual_override`) und `owner_ref`. Host-Aliase durchlaufen dieselbe Hostvalidierung wie bestehende Routen. Zulässige Upstreamheader: Host, X-Forwarded-Host und X-Forwarded-Proto. Antwortheader sind auf CORS, Vary, Content-Security-Policy, Referrer-Policy und X-Content-Type-Options begrenzt; Kontrollzeichen und Backslashes sind gesperrt. Beispiel: `{"response_headers":{"Access-Control-Allow-Origin":"https://example.test"},"upstream_headers":{"Host":"{host}"}}`.

Eine manuelle Ownership muss auf eine vorhandene erkannte Override-Datei zeigen. Die generierte Route wird anschließend ausgelassen; eine doppelte aktive Ownership oder Wildcardüberschneidung ergibt einen Konflikt. Ein geschützter Namespace-Platzhalter kann nicht direkt in einen unkontrollierten manuellen Override umgewandelt werden. Der aktuelle Templateparameter `{$CP_PUBLIC_BASE_DOMAIN}` und der historische Domainparameter werden erkannt.
