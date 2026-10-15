"""Snapshot and restore CIDM state files (P0-06 slice 4).

The real retention drill runs on the operator workstation; here we verify
the planning + application layers: a snapshot captures the right files,
a round-trip restore reproduces them exactly, tampering is detected on
restore via SHA-256 verification, and prune removes expired snapshots.
"""

import json
import os
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backup_jev_state as bjs  # type: ignore  # noqa: E402


def _seed_state(root: Path, *, with_quarantine: bool = True) -> dict:
    """Build a plausible mini-~/.jev tree. Returns a map of relative paths to
    their written bytes so tests can round-trip-compare."""
    files = {
        "operator-console.json": b'{"ok": true}',
        "arsenal/arsenal.db": b"SQLITE binary bytes " + os.urandom(32),
        "arsenal/calibration.jsonl": b'{"kind":"calibration"}\n',
        "arsenal/fast-path.jsonl": b'{"kind":"fast_path"}\n',
        "arsenal/mcp.db": b"SQLITE mcp bytes " + os.urandom(32),
        "arsenal/shadow.jsonl": b'{"kind":"shadow"}\n',
        "sources/one.txt": b"saved source",
        "hermes-skills/skill-a/SKILL.md": b"excluded: symlinked skills",
    }
    if with_quarantine:
        files["arsenal/quarantine/matt-pocock/matt-pocock-tdd/SKILL.md"] = \
            b"excluded: reproducible from upstream"
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return files


def _seed_runs(root: Path) -> dict:
    """Seed a <repo>/runs/ tree for the opt-in --include-runs flag."""
    files = {
        "console-20261015T100000-abc/permits.jsonl": b'{"kind":"permit_issued"}\n',
        "console-20261015T100000-abc/result.json": b'{"status":"complete"}',
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return files


class CollectPathsTests(unittest.TestCase):
    def test_excludes_hermes_skills_and_quarantine_by_default(self):
        with tempfile.TemporaryDirectory() as tds:
            jev = Path(tds)
            _seed_state(jev)
            collected = {rel for _p, rel in bjs._collect_paths(jev, include_runs=False, runs_root=None)}
            self.assertIn("operator-console.json", collected)
            self.assertIn("arsenal/arsenal.db", collected)
            self.assertIn("arsenal/calibration.jsonl", collected)
            self.assertIn("arsenal/mcp.db", collected)
            self.assertIn("sources/one.txt", collected)
            self.assertFalse(any(c.startswith("hermes-skills/") for c in collected))
            self.assertFalse(any(c.startswith("arsenal/quarantine/") for c in collected))

    def test_includes_runs_when_requested(self):
        with tempfile.TemporaryDirectory() as tds_jev, tempfile.TemporaryDirectory() as tds_runs:
            jev = Path(tds_jev)
            runs = Path(tds_runs)
            _seed_state(jev)
            _seed_runs(runs)
            collected = {rel for _p, rel in bjs._collect_paths(jev, include_runs=True, runs_root=runs)}
            self.assertTrue(any(c.startswith("runs/console-") for c in collected))
            self.assertIn("runs/console-20261015T100000-abc/permits.jsonl", collected)


class ManifestTests(unittest.TestCase):
    def test_manifest_has_required_fields_and_per_file_digest(self):
        with tempfile.TemporaryDirectory() as tds:
            jev = Path(tds)
            _seed_state(jev)
            entries = list(bjs._collect_paths(jev, include_runs=False, runs_root=None))
            manifest = bjs._manifest(entries, created_at="2026-10-15T20:00:00Z", host="kens-box")
            self.assertEqual(manifest["created_at"], "2026-10-15T20:00:00Z")
            self.assertEqual(manifest["host"], "kens-box")
            self.assertEqual(manifest["schema"], 1)
            self.assertIsInstance(manifest["files"], list)
            self.assertTrue(all({"name", "sha256", "bytes"} <= set(f) for f in manifest["files"]))

    def test_file_digest_matches_hashlib(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tds:
            p = Path(tds) / "x"
            p.write_bytes(b"hello world")
            self.assertEqual(bjs._file_digest(p),
                             hashlib.sha256(b"hello world").hexdigest())


class SnapshotTests(unittest.TestCase):
    def test_snapshot_creates_tarball_with_manifest_and_files(self):
        with tempfile.TemporaryDirectory() as tds_jev, tempfile.TemporaryDirectory() as tds_snap:
            jev = Path(tds_jev)
            snap_root = Path(tds_snap)
            _seed_state(jev)
            path, manifest = bjs.snapshot(jev, snap_root, include_runs=False,
                                          runs_root=None, now="2026-10-15T20-00-00Z",
                                          host="kens-box")
            self.assertTrue(path.exists())
            self.assertTrue(path.name.endswith(".tar.gz"))
            with tarfile.open(path, "r:gz") as tar:
                names = tar.getnames()
            self.assertIn("MANIFEST.json", names)
            # files in manifest match archive member names (minus MANIFEST.json).
            archive_files = {n for n in names if n != "MANIFEST.json"}
            manifest_names = {f["name"] for f in manifest["files"]}
            self.assertEqual(archive_files, manifest_names)

    def test_snapshot_filename_sorts_by_timestamp(self):
        with tempfile.TemporaryDirectory() as tds_jev, tempfile.TemporaryDirectory() as tds_snap:
            jev = Path(tds_jev)
            snap_root = Path(tds_snap)
            _seed_state(jev)
            earlier, _ = bjs.snapshot(jev, snap_root, now="2026-10-14T20-00-00Z", host="h")
            later, _ = bjs.snapshot(jev, snap_root, now="2026-10-15T20-00-00Z", host="h")
            self.assertLess(earlier.name, later.name)


class RoundTripTests(unittest.TestCase):
    def test_restore_reproduces_every_file_byte_identical(self):
        with tempfile.TemporaryDirectory() as tds_jev, \
                tempfile.TemporaryDirectory() as tds_snap, \
                tempfile.TemporaryDirectory() as tds_scratch:
            jev = Path(tds_jev)
            snap_root = Path(tds_snap)
            scratch = Path(tds_scratch)
            seeded = _seed_state(jev)
            # Trim seeded to what the snapshot actually captured (excludes
            # hermes-skills + quarantine).
            included = {k: v for k, v in seeded.items()
                        if not (k.startswith("hermes-skills/") or k.startswith("arsenal/quarantine/"))}
            path, _manifest = bjs.snapshot(jev, snap_root, now="2026-10-15T20-00-00Z", host="h")
            report = bjs.restore(path, scratch, verify=True)
            self.assertTrue(report["ok"])
            for rel, content in included.items():
                self.assertEqual((scratch / rel).read_bytes(), content, rel)

    def test_restore_detects_tampered_file(self):
        with tempfile.TemporaryDirectory() as tds_jev, \
                tempfile.TemporaryDirectory() as tds_snap, \
                tempfile.TemporaryDirectory() as tds_scratch:
            jev = Path(tds_jev)
            snap_root = Path(tds_snap)
            scratch = Path(tds_scratch)
            _seed_state(jev)
            path, _manifest = bjs.snapshot(jev, snap_root, now="2026-10-15T20-00-00Z", host="h")
            # Rewrite the tarball with the manifest intact but one file content changed.
            tampered = snap_root / "tampered.tar.gz"
            with tarfile.open(path, "r:gz") as src:
                members = src.getmembers()
                blobs = {m.name: src.extractfile(m).read() for m in members if m.isfile()}
            blobs["arsenal/calibration.jsonl"] = b'{"kind":"EVIL"}\n'
            with tarfile.open(tampered, "w:gz") as dst:
                for name, data in blobs.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    import io
                    dst.addfile(info, io.BytesIO(data))
            report = bjs.restore(tampered, scratch, verify=True)
            self.assertFalse(report["ok"])
            self.assertIn("arsenal/calibration.jsonl", report["mismatched"])


class RestoreSafetyTests(unittest.TestCase):
    def test_restore_rejects_path_traversal_entry(self):
        """A malicious snapshot carrying `../etc/passwd` must not escape scratch."""
        with tempfile.TemporaryDirectory() as tds_snap, tempfile.TemporaryDirectory() as tds_scratch:
            path = Path(tds_snap) / "evil.tar.gz"
            manifest = {"schema": 1, "created_at": "x", "host": "x", "files": [
                {"name": "../escape.txt", "sha256": "0" * 64, "bytes": 0}]}
            with tarfile.open(path, "w:gz") as tar:
                raw = json.dumps(manifest).encode()
                info = tarfile.TarInfo("MANIFEST.json")
                info.size = len(raw)
                import io
                tar.addfile(info, io.BytesIO(raw))
                evil = tarfile.TarInfo("../escape.txt")
                evil.size = 0
                import io as _io
                tar.addfile(evil, _io.BytesIO(b""))
            with self.assertRaises(ValueError):
                bjs.restore(path, Path(tds_scratch), verify=True)


class ListSnapshotsTests(unittest.TestCase):
    def test_lists_newest_first(self):
        with tempfile.TemporaryDirectory() as tds_jev, tempfile.TemporaryDirectory() as tds_snap:
            jev = Path(tds_jev)
            snap_root = Path(tds_snap)
            _seed_state(jev)
            bjs.snapshot(jev, snap_root, now="2026-10-14T20-00-00Z", host="h")
            bjs.snapshot(jev, snap_root, now="2026-10-15T20-00-00Z", host="h")
            found = bjs.list_snapshots(snap_root)
            self.assertEqual(len(found), 2)
            self.assertGreaterEqual(found[0]["path"], found[1]["path"])


class PruneTests(unittest.TestCase):
    def test_removes_snapshots_older_than_threshold(self):
        with tempfile.TemporaryDirectory() as tds_jev, tempfile.TemporaryDirectory() as tds_snap:
            jev = Path(tds_jev)
            snap_root = Path(tds_snap)
            _seed_state(jev)
            old, _ = bjs.snapshot(jev, snap_root, now="2026-09-01T00-00-00Z", host="h")
            new, _ = bjs.snapshot(jev, snap_root, now="2026-10-15T00-00-00Z", host="h")
            # Pretend "now" is 2026-10-15, prune > 30 days old.
            removed = bjs.prune(snap_root, older_than_days=30,
                                now_ts=time.mktime(time.strptime("2026-10-15", "%Y-%m-%d")),
                                dry_run=False)
            self.assertEqual(removed, [str(old)])
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())

    def test_dry_run_does_not_delete(self):
        with tempfile.TemporaryDirectory() as tds_jev, tempfile.TemporaryDirectory() as tds_snap:
            jev = Path(tds_jev)
            snap_root = Path(tds_snap)
            _seed_state(jev)
            old, _ = bjs.snapshot(jev, snap_root, now="2026-09-01T00-00-00Z", host="h")
            removed = bjs.prune(snap_root, older_than_days=30,
                                now_ts=time.mktime(time.strptime("2026-10-15", "%Y-%m-%d")),
                                dry_run=True)
            self.assertEqual(removed, [str(old)])
            self.assertTrue(old.exists())


class CliTests(unittest.TestCase):
    def test_snapshot_then_restore_subcommands_round_trip(self):
        import contextlib
        from io import StringIO

        with tempfile.TemporaryDirectory() as tds_jev, \
                tempfile.TemporaryDirectory() as tds_snap, \
                tempfile.TemporaryDirectory() as tds_scratch:
            jev = Path(tds_jev)
            snap_root = Path(tds_snap)
            scratch = Path(tds_scratch)
            _seed_state(jev)
            out = StringIO()
            with contextlib.redirect_stdout(out):
                rc = bjs.main(["snapshot", "--jev-root", str(jev),
                               "--snapshot-root", str(snap_root)])
            self.assertEqual(rc, 0)
            snapshots = list(snap_root.glob("*.tar.gz"))
            self.assertEqual(len(snapshots), 1)
            out2 = StringIO()
            with contextlib.redirect_stdout(out2):
                rc2 = bjs.main(["restore", str(snapshots[0]), "--to", str(scratch)])
            self.assertEqual(rc2, 0)
            self.assertTrue((scratch / "operator-console.json").exists())


if __name__ == "__main__":
    unittest.main()
