import yaml

from dltools.lines import Line
from dltools.render import load_catalog, render

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
