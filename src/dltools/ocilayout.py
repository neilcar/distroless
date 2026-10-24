"""Append a layer to one architecture of an OCI image layout (as written by `apko build`)."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

# Wolfi arch name -> OCI platform architecture.
OCI_ARCH = {"x86_64": "amd64", "aarch64": "arm64"}
LAYER_TYPE = "application/vnd.oci.image.layer.v1.tar+gzip"


def _dump(obj: dict) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode()


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _blob(layout: Path, digest: str) -> Path:
    return layout / "blobs" / "sha256" / digest.removeprefix("sha256:")


def _put_blob(layout: Path, data: bytes) -> str:
    digest = _digest(data)
    path = _blob(layout, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return digest


def append_layer(layout: Path, arch: str, layer: Path, history: str) -> None:
    """Add `layer` (a .tar.gz) on top of the `arch` image; other arches are untouched."""
    layout = Path(layout)
    oci_arch = OCI_ARCH[arch]
    index_path = layout / "index.json"
    index = json.loads(index_path.read_text())
    matches = [m for m in index["manifests"] if m.get("platform", {}).get("architecture") == oci_arch]
    if len(matches) != 1:
        raise ValueError(f"expected one {oci_arch} manifest in {index_path}, found {len(matches)}")
    entry = matches[0]
    if entry["mediaType"] != "application/vnd.oci.image.manifest.v1+json":
        raise ValueError(f"unsupported manifest type {entry['mediaType']}")

    raw = layer.read_bytes()
    diff_id = _digest(gzip.decompress(raw))
    layer_digest = _put_blob(layout, raw)

    manifest = json.loads(_blob(layout, entry["digest"]).read_text())
    config = json.loads(_blob(layout, manifest["config"]["digest"]).read_text())
    config["rootfs"]["diff_ids"].append(diff_id)
    config.setdefault("history", []).append({"created_by": history})
    config_bytes = _dump(config)
    manifest["config"] = {**manifest["config"], "digest": _put_blob(layout, config_bytes),
                          "size": len(config_bytes)}
    manifest["layers"].append(
        {"mediaType": LAYER_TYPE, "size": len(raw), "digest": layer_digest}
    )
    manifest_bytes = _dump(manifest)
    entry["digest"] = _put_blob(layout, manifest_bytes)
    entry["size"] = len(manifest_bytes)
    index_path.write_bytes(_dump(index))
