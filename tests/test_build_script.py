"""Tests for build.py: which executables a release build makes."""

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent

_spec = importlib.util.spec_from_file_location("quickprs_build_script",
                                               ROOT / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def _commands(monkeypatch, extra):
    """The PyInstaller command lines build() runs, without running them."""
    calls = []

    def fake_run(cmd, cwd=None, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(build.subprocess, "run", fake_run)
    build.build(extra)
    return calls


def _by_name(cmds):
    return {cmd[cmd.index("--name") + 1]: cmd for cmd in cmds}


class TestExecutables:

    def test_gui_and_console_builds(self, monkeypatch, tmp_path):
        """A console neither waits for the windowed GUI build nor shows its
        output, so the command line gets a console build of its own."""
        builds = _by_name(_commands(monkeypatch, ["--distpath", str(tmp_path)]))
        assert set(builds) == {"QuickPRS", "QuickPRS-cli"}
        assert "--windowed" in builds["QuickPRS"]
        assert "--console" not in builds["QuickPRS"]
        assert "--console" in builds["QuickPRS-cli"]
        assert "--windowed" not in builds["QuickPRS-cli"]

    def test_builds_bundle_the_same_modules(self, monkeypatch, tmp_path):
        builds = _by_name(_commands(monkeypatch, ["--distpath", str(tmp_path)]))

        def options(cmd):
            cmd = [a for a in cmd if a not in ("--windowed", "--console")]
            i = cmd.index("--name")
            return cmd[:i] + cmd[i + 2:]

        assert options(builds["QuickPRS"]) == options(builds["QuickPRS-cli"])

    def test_extra_options_reach_every_build(self, monkeypatch, tmp_path):
        work = str(tmp_path / "work")
        cmds = _commands(monkeypatch, ["--workpath", work,
                                       "--distpath", str(tmp_path)])
        for cmd in cmds:
            assert cmd[-1] == str(ROOT / "run.py")
            assert cmd[cmd.index("--workpath") + 1] == work

    def test_reports_where_the_executables_are(self, monkeypatch, tmp_path,
                                               capsys):
        (tmp_path / "QuickPRS.exe").write_bytes(b"x" * 2048)
        _commands(monkeypatch, [f"--distpath={tmp_path}"])
        out = capsys.readouterr().out
        assert f"Built: {tmp_path / 'QuickPRS.exe'}" in out
        assert f"{tmp_path / 'QuickPRS-cli.exe'} was not found" in out
