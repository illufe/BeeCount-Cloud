"""Smoke-test the shipped WAL-safe SQLite backup script."""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "backup_sqlite.sh"


def _minimal_path(tmp_path: Path) -> str:
    """Expose the shell tools used by the script, deliberately omitting sqlite3."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("date", "mkdir", "mktemp", "rm"):
        source = shutil.which(name)
        assert source, f"test requires {name}"
        (bin_dir / name).symlink_to(source)
    (bin_dir / "python3").symlink_to(sys.executable)
    return str(bin_dir)


def test_backup_sqlite_script_creates_verified_clean_copy(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    output_dir = tmp_path / "backups"

    source = sqlite3.connect(source_path)
    try:
        assert source.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        source.execute("CREATE TABLE entries (value TEXT NOT NULL)")
        source.execute("INSERT INTO entries(value) VALUES ('committed')")
        source.commit()
        assert source_path.with_name(source_path.name + "-wal").exists()

        bash = shutil.which("bash")
        assert bash
        result = subprocess.run(
            [bash, str(SCRIPT), str(source_path), str(output_dir)],
            env={"PATH": _minimal_path(tmp_path)},
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        source.close()

    assert result.returncode == 0, result.stderr
    targets = sorted(output_dir.glob("beecount-*.db"))
    assert len(targets) == 1
    target_path = targets[0]
    assert not target_path.with_name(target_path.name + "-wal").exists()
    assert not target_path.with_name(target_path.name + "-shm").exists()

    target = sqlite3.connect(target_path)
    try:
        assert target.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert target.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert target.execute("SELECT value FROM entries").fetchone() == ("committed",)
    finally:
        target.close()


def test_backup_sqlite_script_does_not_clobber_racing_target(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    output_dir = tmp_path / "backups"
    output_dir.mkdir()
    fixed_target = output_dir / "beecount-20260823-010203.db"
    marker = tmp_path / "wrapper-ran"

    source = sqlite3.connect(source_path)
    try:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("CREATE TABLE entries (value TEXT NOT NULL)")
        source.execute("INSERT INTO entries(value) VALUES ('committed')")
        source.commit()
    finally:
        source.close()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("mkdir", "mktemp", "rm"):
        source_tool = shutil.which(name)
        assert source_tool
        (bin_dir / name).symlink_to(source_tool)
    date_tool = bin_dir / "date"
    date_tool.write_text("#!/bin/sh\nprintf '%s\\n' '20260823-010203'\n")
    date_tool.chmod(0o755)
    real_python = sys.executable
    wrapper = bin_dir / "python3"
    wrapper.write_text(
        "#!" + real_python + "\n"
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        f"real = {real_python!r}\n"
        f"marker = {str(marker)!r}\n"
        f"target = {str(fixed_target)!r}\n"
        "if sys.argv[1:2] == ['-'] and not os.path.exists(marker):\n"
        "    result = subprocess.run([real, *sys.argv[1:]])\n"
        "    if result.returncode == 0:\n"
        "        with open(target, 'wb') as stream:\n"
        "            stream.write(b'original')\n"
        "        open(marker, 'wb').close()\n"
        "    raise SystemExit(result.returncode)\n"
        "os.execv(real, [real, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o755)

    bash = shutil.which("bash")
    assert bash
    result = subprocess.run(
        [bash, str(SCRIPT), str(source_path), str(output_dir)],
        env={"PATH": str(bin_dir)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert fixed_target.read_bytes() == b"original"
    assert not list(output_dir.glob(".beecount-*.tmp.*"))
