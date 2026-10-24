import gzip
import hashlib
import json
import shutil
import tarfile

import pytest

from dltools.cli import main
from dltools.ocilayout import append_layer


def blob(layout, digest):
    return layout / "blobs/sha256" / digest.removeprefix("sha256:")


def manifests(layout):
    index = json.loads((layout / "index.json").read_text())
    return {m["platform"]["architecture"]: m for m in index["manifests"]}


@pytest.fixture
def layer(tmp_path):
    src = tmp_path / "f"
    src.write_text("vendored")
    out = tmp_path / "layer.tar.gz"
    with gzip.GzipFile(out, "wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
        tar.add(src, arcname="opt/f")
    return out


def check_integrity(layout):
    """What `crane validate` checks for a registry image: every descriptor resolves and matches."""
    for entry in manifests(layout).values():
        raw = blob(layout, entry["digest"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["digest"].removeprefix("sha256:")
        assert len(raw) == entry["size"]
        manifest = json.loads(raw)
        cfg_raw = blob(layout, manifest["config"]["digest"]).read_bytes()
        assert hashlib.sha256(cfg_raw).hexdigest() == manifest["config"]["digest"][7:]
        assert len(cfg_raw) == manifest["config"]["size"]
        config = json.loads(cfg_raw)
        assert len(config["rootfs"]["diff_ids"]) == len(manifest["layers"])
        for desc, diff_id in zip(manifest["layers"], config["rootfs"]["diff_ids"]):
            data = blob(layout, desc["digest"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == desc["digest"][7:]
            assert len(data) == desc["size"]
            assert "sha256:" + hashlib.sha256(gzip.decompress(data)).hexdigest() == diff_id


def test_append_layer_updates_one_arch(static_layout, layer, tmp_path):
    layout = tmp_path / "oci"
    shutil.copytree(static_layout, layout)
    before = manifests(layout)
    old_manifest = json.loads(blob(layout, before["amd64"]["digest"]).read_text())
    old_config = json.loads(blob(layout, old_manifest["config"]["digest"]).read_text())

    append_layer(layout, "x86_64", layer, "vendor layer")

    after = manifests(layout)
    assert after["arm64"] == before["arm64"]
    assert after["amd64"]["digest"] != before["amd64"]["digest"]
    manifest = json.loads(blob(layout, after["amd64"]["digest"]).read_text())
    assert len(manifest["layers"]) == len(old_manifest["layers"]) + 1
    top = manifest["layers"][-1]
    assert top["digest"] == "sha256:" + hashlib.sha256(layer.read_bytes()).hexdigest()
    assert top["size"] == layer.stat().st_size
    assert blob(layout, top["digest"]).read_bytes() == layer.read_bytes()
    config = json.loads(blob(layout, manifest["config"]["digest"]).read_text())
    diff_id = "sha256:" + hashlib.sha256(gzip.decompress(layer.read_bytes())).hexdigest()
    assert config["rootfs"]["diff_ids"] == old_config["rootfs"]["diff_ids"] + [diff_id]
    assert len(config["history"]) == len(old_config["history"]) + 1
    assert config["architecture"] == "amd64"
    check_integrity(layout)


def test_append_layer_cli(static_layout, layer, tmp_path):
    layout = tmp_path / "oci"
    shutil.copytree(static_layout, layout)
    assert main(["append-layer", "--layout", str(layout), "--arch", "aarch64",
                 "--layer", str(layer)]) == 0
    manifest = json.loads(blob(layout, manifests(layout)["arm64"]["digest"]).read_text())
    assert manifest["layers"][-1]["digest"].endswith(hashlib.sha256(layer.read_bytes()).hexdigest())
    check_integrity(layout)
