import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

GEN = runpy.run_path(str(Path(__file__).resolve().parent.parent / "scripts" / "aur-pkgbuild"))


def dist(name, version, requires=(), file=None):
    file = file or f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
    return {"metadata": {"name": name, "version": version, "requires_dist": list(requires)},
            "download_info": {"url": f"https://files.example/{file}",
                              "archive_info": {"hashes": {"sha256": "ab" * 32}}}}


REPORT = [
    dist("thermoslop", "1.0.0", ["aiohomekit>=3.2", "mcp<3,>=2.3"]),
    dist("aiohomekit", "4.0.1", ["zeroconf (>=0.149.16)", "async-timeout ; python_version < '3.11'"]),
    dist("mcp", "2.3.0", ["pydantic>=2.12.0", "pywin32>=311; sys_platform == 'win32'"]),
    dist("zeroconf", "0.151.5", ["ifaddr>=0.1.7"], file="zeroconf-0.151.5-cp314-cp314-manylinux_x86_64.whl"),
    dist("pydantic", "2.14.1", ["pydantic-core==2.50.1"]),
    dist("pydantic_core", "2.50.1"),
    dist("ifaddr", "0.2.0"),
]


def test_depends_lists_only_what_we_require_directly_with_our_bounds():
    depends, vendored = GEN["plan"](REPORT)
    # pydantic-core and ifaddr come with Arch's pydantic and zeroconf; markers for
    # other platforms and old Pythons are dropped.
    assert depends == ["python", "python-pydantic>=2.12.0", "python-zeroconf>=0.149.16"]
    assert [f for f, _, _ in vendored] == ["aiohomekit-4.0.1-py3-none-any.whl", "mcp-2.3.0-py3-none-any.whl"]


def test_a_dependency_in_neither_table_stops_the_script():
    with pytest.raises(SystemExit, match="Not in ARCH or VENDORED: brand-new"):
        GEN["plan"](REPORT + [dist("brand_new", "1.0")])


def test_a_compiled_wheel_cant_be_vendored(monkeypatch):
    monkeypatch.setitem(GEN["plan"].__globals__, "VENDORED", GEN["VENDORED"] | {"zeroconf"})
    monkeypatch.setitem(GEN["plan"].__globals__, "ARCH", {k: v for k, v in GEN["ARCH"].items() if k != "zeroconf"})
    with pytest.raises(SystemExit, match="isn't pure Python"):
        GEN["plan"](REPORT)


@pytest.mark.skipif(sys.platform != "linux", reason="PKGBUILDs are read by Arch's bash; macOS ships bash 3.2")
def test_pkgbuild_is_valid_bash_with_matching_sources_and_sums(tmp_path):
    depends, vendored = GEN["plan"](REPORT + [dist("chacha20poly1305", "0.0.3", file="chacha20poly1305-0.0.3.tar.gz")])
    text = GEN["pkgbuild"]("1.0.0", "cd" * 32, depends, vendored)
    (tmp_path / "PKGBUILD").write_text(text)
    out = subprocess.run(["bash", "-c", 'set -e; source PKGBUILD; '
                          'echo "${#source[@]} ${#sha256sums[@]} ${#noextract[@]} ${source[0]}"'],
                         cwd=tmp_path, capture_output=True, text=True, check=True).stdout.split()
    assert out[:3] == ["4", "4", "2"]  # thermoslop sdist + 2 wheels + 1 sdist; only wheels skip extraction
    assert out[3].endswith("/thermoslop-1.0.0.tar.gz")  # $pkgver expands (double quotes)
    assert 'cd "$srcdir/chacha20poly1305-0.0.3"\n  python -m build' in text
    assert "&&" not in text  # makepkg's errexit doesn't catch a failed `cd` inside `&&`


@pytest.mark.skipif(not shutil.which("makepkg"), reason="needs makepkg (Arch)")
def test_committed_srcinfo_matches_the_pkgbuild():
    aur = Path(__file__).resolve().parent.parent / "packaging" / "aur"
    if not (aur / "PKGBUILD").exists():
        pytest.skip("not in a checkout")
    srcinfo = subprocess.run(["makepkg", "--printsrcinfo"], cwd=aur, capture_output=True, text=True, check=True)
    assert (aur / ".SRCINFO").read_text() == srcinfo.stdout
