#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Hardware-free checks for the installers' macOS storage guard."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "tools/installer-macos-guard.sh"
FLAG = "--this-mac-does-not-run-macos"
CONFIRMATION = "this Mac does not run macOS"
REFUSED = (
    "Stopped before changing anything: T2Touch can't rule out macOS on this Mac."
)
HARM_START = "On our test Mac, after T2Touch had run in Linux, macOS removed"
KEYCHAIN = (
    "The old login keychain no longer\nopens with the account's password."
)

LINUX_ONLY = (
    'PATH="/dev/nvme0n1" TYPE="disk" PARTTYPE="" FSTYPE=""\n'
    'PATH="/dev/nvme0n1p1" TYPE="part" '
    'PARTTYPE="c12a7328-f81f-11d2-ba4b-00a0c93ec93b" FSTYPE="vfat"\n'
    'PATH="/dev/nvme0n1p2" TYPE="part" '
    'PARTTYPE="0fc63daf-8483-4772-8e79-3d69d8477de4" FSTYPE="crypto_LUKS"\n'
    'PATH="/dev/mapper/root" TYPE="crypt" PARTTYPE="" FSTYPE="btrfs"\n'
    'PATH="/dev/zram0" TYPE="disk" PARTTYPE="" FSTYPE="swap"\n'
)
APFS_PARTITION = (
    'PATH="/dev/nvme0n1p3" TYPE="part" '
    'PARTTYPE="7C3457EF-0000-11AA-AA11-00306543ECAC" FSTYPE="apfs"\n'
)


class MacosGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        self.calls = Path(self.tmp.name) / "calls"
        self.calls.touch()
        self.listing = Path(self.tmp.name) / "listing"

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def fake_lsblk(self, listing, status=0):
        self.listing.write_text(listing, encoding="utf-8")
        self.stub(
            "lsblk",
            f'printf "%s\\n" "$*" >>"{self.calls}.lsblk"\n'
            f'cat "{self.listing}"\nexit {status}\n',
        )

    def record_calls(self, *names):
        for name in names:
            self.stub(name, f'printf "{name} %s\\n" "$*" >>"{self.calls}"\nexit 0\n')

    def env(self, **extra):
        environment = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": self.tmp.name,
            "LC_ALL": "C",
        }
        environment.update(extra)
        return environment

    def guard(self, override=0, answer=""):
        return subprocess.run(
            [
                "bash",
                "-c",
                'set -euo pipefail; source "$1"; '
                'refuse_if_macos_possible "$2"',
                "guard",
                str(GUARD),
                str(override),
            ],
            input=answer,
            env=self.env(),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_linux_only_storage_passes_silently(self):
        self.fake_lsblk(LINUX_ONLY)
        result = self.guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            (Path(f"{self.calls}.lsblk")).read_text(encoding="utf-8"),
            "--noheadings --pairs --output PATH,TYPE,PARTTYPE,FSTYPE\n",
        )

    def test_apple_storage_refuses_and_names_each_device(self):
        cases = {
            "apfs partition": APFS_PARTITION,
            "hfs+ partition": 'PATH="/dev/sda2" TYPE="part" '
            'PARTTYPE="48465300-0000-11aa-aa11-00306543ecac" FSTYPE=""\n',
            "core storage": 'PATH="/dev/sda3" TYPE="part" '
            'PARTTYPE="53746f72-6167-11aa-aa11-00306543ecac" FSTYPE=""\n',
            "apple partition map": 'PATH="/dev/sdb2" TYPE="part" '
            'PARTTYPE="Apple_HFS" FSTYPE=""\n',
            "unpartitioned hfs+ disk": 'PATH="/dev/sdc" TYPE="disk" '
            'PARTTYPE="" FSTYPE="hfsplus"\n',
            "apfs on a non-apple type": 'PATH="/dev/sdd1" TYPE="part" '
            'PARTTYPE="ebd0a0a2-b9e5-4433-87c0-68b6b72699c7" FSTYPE="apfs"\n',
        }
        for name, row in cases.items():
            with self.subTest(name):
                self.fake_lsblk(LINUX_ONLY + row)
                result = self.guard()
                self.assertEqual(result.returncode, 1)
                device = row.split('"')[1]
                self.assertIn(f"  {device}: Apple ", result.stderr)
                self.assertIn(REFUSED, result.stderr)
                self.assertIn('"Macs that also run macOS"', result.stderr)
                self.assertIn(f"rerun with\n{FLAG}.", result.stderr)
                self.assertNotIn("nvme0n1p2", result.stderr)

    def test_storage_that_cannot_be_checked_refuses(self):
        cases = {
            "unreadable partition type": (
                LINUX_ONLY
                + 'PATH="/dev/sda1" TYPE="part" PARTTYPE="" FSTYPE=""\n',
                0,
                "/dev/sda1: partition type unreadable",
            ),
            "unexpected output": (
                LINUX_ONLY + "NAME=sda1\n",
                0,
                "lsblk output not understood: NAME=sda1",
            ),
            "empty listing": ("", 0, "lsblk listed no disks"),
            "lsblk failure": ("lsblk: failed to access sysfs\n", 32,
                              "lsblk could not list the disks: lsblk: failed"),
        }
        for name, (listing, status, message) in cases.items():
            with self.subTest(name):
                self.fake_lsblk(listing, status)
                result = self.guard()
                self.assertEqual(result.returncode, 1)
                self.assertIn(message, result.stderr)
                self.assertIn(REFUSED, result.stderr)

    def test_missing_lsblk_refuses(self):
        result = subprocess.run(
            [
                "/bin/bash",
                "-c",
                'source "$1"; refuse_if_macos_possible 0',
                "guard",
                str(GUARD),
            ],
            env={"PATH": str(self.bin), "LC_ALL": "C"},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("lsblk could not list the disks", result.stderr)

    def test_override_requires_the_typed_statement(self):
        self.fake_lsblk(LINUX_ONLY + APFS_PARTITION)
        for answer in ("", "yes\n", "This Mac does not run macOS\n",
                       "this Mac does not run\n"):
            with self.subTest(answer=answer):
                result = self.guard(override=1, answer=answer)
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"To continue, type: {CONFIRMATION}", result.stderr)
                self.assertIn("Not confirmed. Stopped before changing anything.",
                              result.stderr)

        result = self.guard(override=1, answer=f"{CONFIRMATION}\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/dev/nvme0n1p3: Apple partition type", result.stderr)
        self.assertNotIn("Not confirmed", result.stderr)

    def test_keychain_harm_comes_before_the_findings_and_the_flag(self):
        self.fake_lsblk(LINUX_ONLY + APFS_PARTITION)
        refused = self.guard().stderr
        self.assertTrue(refused.startswith(f"{REFUSED}\n\n{HARM_START}"), refused)
        self.assertLess(refused.index(KEYCHAIN), refused.index("Found:\n"))
        self.assertLess(refused.index("Found:\n"), refused.index(FLAG))

        prompt = self.guard(override=1, answer=f"{CONFIRMATION}\n").stderr
        self.assertTrue(
            prompt.startswith(
                f"T2Touch can't rule out macOS on this Mac.\n\n{HARM_START}"
            ),
            prompt,
        )
        self.assertLess(prompt.index(KEYCHAIN), prompt.index("Found:\n"))
        self.assertLess(prompt.index("Found:\n"),
                        prompt.index(f"To continue, type: {CONFIRMATION}"))

    def test_install_sh_refuses_before_packages_or_root_check(self):
        # Covers both package-manager paths: with "omarchy" on PATH (the
        # omarchy pkg add branch) and without it (the pacman/dnf/apt-get
        # branches). Either way, the macOS guard must run before any of them,
        # and before install.sh's own root check.
        self.fake_lsblk(LINUX_ONLY + APFS_PARTITION)
        self.record_calls(
            "omarchy", "pacman", "dnf", "apt-get", "make", "install", "mkdir",
        )
        for omarchy_present in (True, False):
            if not omarchy_present:
                (self.bin / "omarchy").unlink()
            with self.subTest(omarchy_present=omarchy_present):
                for args in ([], ["--prepare-transport-update"],
                             ["--prepare-native-recovery"]):
                    with self.subTest(args=args):
                        self.calls.write_text("", encoding="utf-8")
                        result = subprocess.run(
                            ["bash", str(ROOT / "install.sh"), *args],
                            env=self.env(SUDO_USER="tester"),
                            text=True,
                            capture_output=True,
                            check=False,
                        )
                        self.assertEqual(result.returncode, 1, result.stderr)
                        self.assertIn(REFUSED, result.stderr)
                        self.assertNotIn("Run with sudo", result.stderr)
                        self.assertEqual(
                            self.calls.read_text(encoding="utf-8"), ""
                        )

    def test_install_sh_refuses_before_any_other_step(self):
        self.fake_lsblk(LINUX_ONLY + APFS_PARTITION)
        self.record_calls("make", "modinfo", "systemctl", "install", "sed")
        for args in ([], ["--prepare-transport-update"],
                     ["--prepare-native-recovery"]):
            with self.subTest(args=args):
                result = subprocess.run(
                    ["bash", str(ROOT / "install.sh"), *args],
                    env=self.env(SUDO_USER="tester"),
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(REFUSED, result.stderr)
                self.assertNotIn("Run with sudo", result.stderr)
                self.assertEqual(self.calls.read_text(encoding="utf-8"), "")

    def test_install_sh_flag_alone_still_asks_for_the_statement(self):
        self.fake_lsblk(LINUX_ONLY + APFS_PARTITION)
        self.record_calls("make", "modinfo", "systemctl", "install", "sed")
        refused = subprocess.run(
            ["bash", str(ROOT / "install.sh"), FLAG],
            input="yes\n",
            env=self.env(SUDO_USER="tester"),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(refused.returncode, 1)
        self.assertIn(f"To continue, type: {CONFIRMATION}", refused.stderr)
        self.assertIn("Not confirmed. Stopped before changing anything.",
                      refused.stderr)
        self.assertEqual(self.calls.read_text(encoding="utf-8"), "")

        confirmed = subprocess.run(
            ["bash", str(ROOT / "install.sh"), FLAG],
            input=f"{CONFIRMATION}\n",
            env=self.env(SUDO_USER="tester"),
            text=True,
            capture_output=True,
            check=False,
        )
        # Past the guard, the root check stops the unprivileged test run.
        self.assertEqual(confirmed.returncode, 1)
        self.assertTrue(
            confirmed.stderr.endswith("Run with sudo: sudo ./install.sh\n"),
            confirmed.stderr,
        )

    def test_install_sh_wrong_statement_changes_nothing(self):
        # With "omarchy" on PATH, so a wrong statement must stop before the
        # omarchy pkg add branch runs, not just before a pacman/dnf/apt-get one.
        self.fake_lsblk(LINUX_ONLY + APFS_PARTITION)
        self.record_calls("omarchy", "pacman", "make", "install", "mkdir")
        result = subprocess.run(
            ["bash", str(ROOT / "install.sh"), FLAG],
            input="this Mac runs macOS\n",
            env=self.env(SUDO_USER="tester"),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Not confirmed. Stopped before changing anything.",
                      result.stderr)
        self.assertEqual(self.calls.read_text(encoding="utf-8"), "")

    def test_install_sh_continues_past_guard_without_apple_storage(self):
        # The override flag is harmless (no prompt fires) when nothing was
        # found, whether or not it was actually needed.
        self.fake_lsblk(LINUX_ONLY)
        for args in ([], [FLAG], ["--prepare-native-recovery", FLAG]):
            with self.subTest(args=args):
                result = subprocess.run(
                    ["bash", str(ROOT / "install.sh"), *args],
                    env=self.env(),
                    text=True,
                    capture_output=True,
                    check=False,
                )
                # The next check, for root, stops the unprivileged test run.
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    result.stderr, "Run with sudo: sudo ./install.sh\n"
                )

    def test_installers_reject_unknown_or_repeated_arguments(self):
        self.fake_lsblk(LINUX_ONLY)
        self.record_calls("omarchy", "pacman")
        for args in (
            ["--unknown"],
            [FLAG, FLAG],
            ["--prepare-transport-update", "--prepare-native-recovery"],
        ):
            with self.subTest(args=args):
                result = subprocess.run(
                    ["bash", str(ROOT / "install.sh"), *args],
                    env=self.env(),
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("Usage:", result.stderr)
                self.assertFalse(Path(f"{self.calls}.lsblk").exists())
                self.assertEqual(self.calls.read_text(encoding="utf-8"), "")

    def test_guard_precedes_every_installer_change(self):
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        guard = 'refuse_if_macos_possible "$macos_override" || exit 1'
        for later in (
            "if [[ $EUID -ne 0 ]]",
            'source "$source_dir/tools/installer-kernel.sh"',
            "install_dependencies",
            'make -C "$source_dir/src"',
            "prepare_transport_update",
            "target_dir=/opt/t2-touchid",
        ):
            self.assertLess(installer.index(guard), installer.index(later))


if __name__ == "__main__":
    unittest.main()
