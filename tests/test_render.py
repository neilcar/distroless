import yaml

from dltools.lines import Line
from dltools.render import load_catalog, render, render_vendor

CATALOG = load_catalog("catalog.yaml")
PY = Line("python", "3.12", "python-3.12", "3.12.15-r6")
NGINX = Line("nginx", "stable", "nginx-stable", "1.30.2-r0")
STATIC = Line("static", "latest", "ca-certificates-bundle", "20260909-r3")


def pkgs(cfg):
    return cfg["contents"]["packages"]


def test_render_python_runtime_has_no_shell_or_apk():
    cfg = render(CATALOG, PY, "runtime")
    assert "python-3.12=3.12.15-r6" in pkgs(cfg)
    assert {"wolfi-baselayout", "ca-certificates-bundle", "tzdata"} <= set(pkgs(cfg))
    assert not {"busybox", "apk-tools", "bash"} & set(pkgs(cfg))
    assert cfg["accounts"]["run-as"] == "65532"
    assert cfg["accounts"]["users"][0]["uid"] == 65532
    assert cfg["archs"] == ["x86_64", "aarch64"]
    assert cfg["entrypoint"]["command"] == "/usr/bin/python3.12"
    assert cfg["annotations"]["org.opencontainers.image.source"] == (
        "https://github.com/neilcar/distroless"
    )


def test_render_python_dev_adds_tools():
    cfg = render(CATALOG, PY, "dev")
    assert {"python-3.12=3.12.15-r6", "busybox", "py3.12-pip", "uv"} <= set(pkgs(cfg))


def test_render_nginx_uses_local_config_package():
    cfg = render(CATALOG, NGINX, "runtime")
    assert {
        "nginx-stable=1.30.2-r0", "nginx-stable-mime-types", "distroless-nginx-config",
    } <= set(pkgs(cfg))
    assert "nginx-stable-config" not in pkgs(cfg)
    assert "./packages" in cfg["contents"]["repositories"]
    assert "./melange.rsa.pub" in cfg["contents"]["keyring"]
    assert cfg["entrypoint"]["command"] == "/usr/sbin/nginx"
    assert cfg["cmd"] == "-g 'daemon off;'"
    assert {"path": "/tmp", "type": "directory", "permissions": 0o1777, "uid": 0, "gid": 0} in (
        cfg["paths"]
    )


def test_render_static_minimal():
    cfg = render(CATALOG, STATIC, "runtime")
    assert sorted(pkgs(cfg)) == sorted(
        ["wolfi-baselayout", "ca-certificates-bundle=20260909-r3", "tzdata"]
    )
    assert "entrypoint" not in cfg


def test_render_is_yaml_serialisable():
    assert yaml.safe_load(yaml.safe_dump(render(CATALOG, PY, "dev"))) == render(CATALOG, PY, "dev")


def test_render_nginx_compiled_in_paths_writable_by_nonroot():
    paths = {p["path"]: p for p in render(CATALOG, NGINX, "runtime")["paths"]}
    for d in ("/var/lib/nginx", "/var/lib/nginx/logs", "/var/lib/nginx/tmp"):
        assert paths[d]["type"] == "directory"
        assert (paths[d]["uid"], paths[d]["gid"]) == (65532, 65532)


def test_render_run_as_override():
    catalog = {**CATALOG, "images": {**CATALOG["images"], "root-img": {
        "run_as": "0", "variants": {"runtime": {"packages": []}}}}}
    line = Line("root-img", "latest", "ca-certificates-bundle", "1-r0")
    assert render(catalog, line, "runtime")["accounts"]["run-as"] == "0"
    assert render(CATALOG, STATIC, "runtime")["accounts"]["run-as"] == "65532"
    assert CATALOG["accounts"]["run-as"] == "65532"  # the shared default is not mutated


def test_render_vendor_written_per_line():
    vendor = [{"name": "tool", "version": "1", "kind": "binary", "prefix": "/opt/tool",
               "files": {"x86_64": {"url": "u", "sha256": "s"}}, "launchers": ["tool"]}]
    catalog = {**CATALOG, "images": {**CATALOG["images"], "v-img": {
        "vendor": vendor, "variants": {"runtime": {"packages": []}}}}}
    line = Line("v-img", "latest", "ca-certificates-bundle", "1-r0")
    assert render_vendor(catalog, line) == {"vendor": vendor}
    assert render_vendor(CATALOG, STATIC) is None


def test_render_photoprism_base_no_shell_stub_in_runtime_only():
    line = Line("photoprism-base", "latest", "distroless-libvips", "8.18.7-r0")
    runtime, dev = render(CATALOG, line, "runtime"), render(CATALOG, line, "dev")
    assert "distroless-no-shell" in pkgs(runtime) and "bash" not in pkgs(runtime)
    assert "distroless-no-shell" not in pkgs(dev) and "bash" in pkgs(dev)
    assert "./packages" in runtime["contents"]["repositories"]
    assert "./melange.rsa.pub" in runtime["contents"]["keyring"]


def test_render_photoprism_base_uses_local_libvips():
    line = Line("photoprism-base", "latest", "distroless-libvips", "8.18.7-r0")
    runtime, dev = render(CATALOG, line, "runtime"), render(CATALOG, line, "dev")
    for cfg in (runtime, dev):
        assert "distroless-libvips=8.18.7-r0" in pkgs(cfg)
        assert not {"libvips", "libvips-dev"} & set(pkgs(cfg))
    assert "distroless-libvips-dev" in pkgs(dev)
    assert "distroless-libvips-dev" not in pkgs(runtime)


def test_render_photoprism_base_dev_build_tools():
    line = Line("photoprism-base", "latest", "distroless-libvips", "8.18.7-r0")
    runtime, dev = pkgs(render(CATALOG, line, "runtime")), pkgs(render(CATALOG, line, "dev"))
    assert {"gnutar", "rsync", "wget", "coreutils", "nodejs-24", "npm"} <= set(dev)
    assert "nodejs-22" not in dev
    assert not {"gnutar", "rsync", "wget", "coreutils", "nodejs-24", "npm"} & set(runtime)
