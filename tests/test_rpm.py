"""Finding Harris RPM and handing it a personality (quickprs.rpm)."""

from quickprs import rpm

EXE = r"C:\Program Files (x86)\Harris Radio Personality Manager\RadPersMgr.exe"


def test_exe_from_command():
    assert rpm.exe_from_command(f'"{EXE}" "%1"') == EXE
    assert rpm.exe_from_command(
        r"C:\PROGRA~2\HARRIS~1\RadPersMgr.exe %1") == (
        r"C:\PROGRA~2\HARRIS~1\RadPersMgr.exe")
    assert rpm.exe_from_command(r"C:\Tools\viewer.exe") == (
        r"C:\Tools\viewer.exe")
    assert rpm.exe_from_command("") is None
    assert rpm.exe_from_command(None) is None
    assert rpm.exe_from_command('"unclosed') is None


def test_find_rpm_from_the_prs_association():
    found = rpm.find_rpm(command=f'"{EXE}" "%1"', environ={},
                         exists=lambda p: p == EXE)
    assert found == EXE


def test_find_rpm_ignores_another_program_for_prs():
    """.PRS opening in something else (QuickPRS, an editor) is not RPM;
    RPM's install folder is tried instead."""
    other = r"C:\Tools\QuickPRS.exe"
    env = {"ProgramFiles(x86)": r"C:\Program Files (x86)"}
    assert rpm.find_rpm(command=f'"{other}" "%1"', environ=env,
                        exists=lambda p: p in (other, EXE)) == EXE
    assert rpm.find_rpm(command=f'"{other}" "%1"', environ=env,
                        exists=lambda p: p == other) is None


def test_find_rpm_needs_the_program_to_exist():
    env = {"ProgramFiles(x86)": r"C:\Program Files (x86)",
           "ProgramFiles": r"C:\Program Files"}
    assert rpm.find_rpm(command=f'"{EXE}" "%1"', environ=env,
                        exists=lambda p: False) is None
    in_64 = r"C:\Program Files\Harris Radio Personality Manager\RadPersMgr.exe"
    assert rpm.find_rpm(command="", environ=env,
                        exists=lambda p: p == in_64) == in_64


def test_open_in_rpm(tmp_path):
    calls = []

    def popen(args, cwd=None):
        calls.append((args, cwd))
        return "started"

    prs = tmp_path / "radio.PRS"
    assert rpm.open_in_rpm(prs, EXE, popen=popen) == "started"
    assert calls == [([EXE, str(prs.resolve())], str(tmp_path.resolve()))]
