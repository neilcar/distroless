from dltools.lines import Line
from dltools.tags import tags

H = "0123456789abcdef"


def test_tags_python_runtime():
    assert tags(Line("python", "3.12", "python-3.12", "3.12.15-r6"), "runtime", H) == [
        "3.12", "3.12.15", "3.12.15-01234567",
    ]


def test_tags_python_dev():
    assert tags(Line("python", "3.12", "python-3.12", "3.12.15-r6"), "dev", H) == [
        "3.12-dev", "3.12.15-dev", "3.12.15-01234567-dev",
    ]


def test_tags_nginx():
    assert tags(Line("nginx", "stable", "nginx-stable", "1.30.2-r0"), "runtime", H) == [
        "stable", "1.30", "1.30.2", "1.30.2-01234567",
    ]


def test_tags_static():
    assert tags(Line("static", "latest", "ca-certificates-bundle", "20260909-r3"), "runtime", H) == [
        "latest", "01234567",
    ]
