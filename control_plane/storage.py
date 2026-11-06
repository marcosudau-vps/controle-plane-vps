from datetime import datetime, timezone
from . import models, runtime


def storage_inventory(db):
    summary = runtime.backend.json_lines(["system", "df", "--format", "{{json .}}"])
    containers = runtime.backend.containers()
    referenced = {c["image_id"] for c in containers}
    for release in db.query(models.DeploymentRelease):
        referenced.update(release.images.values())
        referenced.update(release.previous_images.values())
    # Tags and configured image references are retained, even when no container exists.
    for source in db.query(models.DeploymentSource):
        try:
            referenced.add(runtime.backend.image(source.image_ref)["id"])
        except runtime.DockerUnavailable:
            pass
    all_images = runtime.backend.json_lines(
        ["image", "ls", "--no-trunc", "--format", "{{json .}}"]
    )
    tagged = {
        i["ID"]
        for i in all_images
        if i.get("Tag") not in {"<none>", None}
        or i.get("Repository") not in {"<none>", None}
    }
    referenced.update(tagged)
    candidates = []
    for i in all_images:
        if i["ID"] not in referenced:
            candidates.append(
                {
                    "image_id": i["ID"],
                    "size": i.get("Size"),
                    "reason": "dangling and not referenced by any container, configured source or release",
                }
            )
    unique = {i["image_id"]: i for i in candidates}
    volumes = runtime.backend.json_lines(["volume", "ls", "--format", "{{json .}}"])
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source": "docker",
        "summary": summary,
        "containers": containers,
        "images": all_images,
        "volumes": [{"name": v.get("Name"), "protected": True} for v in volumes],
        "cleanup_candidates": list(unique.values()),
        "protected_image_ids": sorted(referenced),
        "cleanup_execution_enabled": False,
        "size_note": "Docker sizes share layers and are not additive. Build cache is reported in summary; no blanket cache or volume deletion.",
    }
