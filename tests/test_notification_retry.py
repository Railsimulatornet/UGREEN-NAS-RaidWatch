"""Notification retries with synthetic status reports and a local mail stub."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("RAIDWATCH_SOURCE", REPO / "raidwatch/raidwatch.sh"))
SOURCE = SCRIPT.read_text()


def function(name):
    return re.search(r"^" + re.escape(name) + r"\(\) \{\n.*?^\}", SOURCE, re.M | re.S).group(0)


class NotificationRetryTests(unittest.TestCase):
    def check_retry(self, previous_problem, current_problem, alert_on_change):
        with tempfile.TemporaryDirectory(prefix="raid mail retry ") as temporary:
            root = Path(temporary)
            state = root / "state.env"
            initial = f'LAST_HASH="previous"\nLAST_PROBLEM="{previous_problem}"\nLAST_ALERT_EPOCH="1700000000"\n'
            state.write_text(initial)
            calls = root / "mail-calls"
            first_state = root / "after-failure.env"
            env = dict(os.environ, STATE_FILE=str(state), TEST_MAIL="0", MAIL_FORMAT="text", FORCE_SEND="0",
                       ALERT_ON_CHANGE=alert_on_change, ALERT_COOLDOWN_SECONDS="3600", LOG_NO_CHANGE_RUNS="0",
                       SUBJECT_PREFIX="[TEST]", NAS_NAME="fixture", TEST_REPORT=current_problem + "|synthetic status",
                       TEST_CALLS=str(calls), FIRST_STATE=str(first_state))
            code = "set -euo pipefail\n" + "\n".join(function(name) for name in ("load_state", "save_state", "main_once")) + """
date() { printf 1700000000; }
build_report_text() { printf '%s' "$TEST_REPORT"; }
hash_text() { printf current; }
is_en() { return 0; }
localize_kind() { printf '%s' "$1"; }
msg() { printf '%s' "$1"; }
log() { :; }
attempts=0
send_mail() {
  attempts=$((attempts + 1))
  printf '%s\\n' "$1" >> "$TEST_CALLS"
  [ "$attempts" -gt 1 ]
}
if main_once; then exit 90; fi
cp -- "$STATE_FILE" "$FIRST_STATE"
main_once
"""
            result = subprocess.run(["bash", "-c", code], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(first_state.read_text(), initial, "Failed delivery must preserve the previous state.")
            self.assertEqual(len(calls.read_text().splitlines()), 2)
            self.assertIn('LAST_HASH="current"', state.read_text())
            self.assertIn(f'LAST_PROBLEM="{current_problem}"', state.read_text())

    def test_failed_recovery_is_retried(self):
        self.check_retry("1", "0", "0")

    def test_failed_change_is_retried(self):
        self.check_retry("0", "0", "1")

    def test_failed_alarm_is_not_suppressed_by_cooldown(self):
        self.check_retry("0", "1", "0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
