# Original source import

Baseline of the existing Control Plane before modernization. Python application, tests,
pyproject and Dockerfile are unchanged. Generated egg-info, caches and installed
virtual environments are omitted. `docs/existing` contains existing service documentation;
`compose.production-reference.yml` is the existing deployment reference, not a portable
or development stack. It references external configuration and protected secret files.

The Dockerfile uses the externally built `selfhost/caddy-cloudflare:local` image to obtain
Caddy with the Cloudflare plugin. That separate service is not included here. Python
console scripts, including selfhostctl, are declared in pyproject.toml; the installed
host launcher has an environment-specific shebang and is not copied.

No production database, data directories, secrets, credentials or backups belong in this
public source repository. Complete operational backups are held separately and privately.
