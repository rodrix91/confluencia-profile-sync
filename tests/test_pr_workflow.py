"""Safety contract for pull-request checks: inspection only, never publication."""

from pathlib import Path
import unittest

WORKFLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/pr-contracts.yml").read_text(encoding="utf-8")


class PullRequestWorkflowContract(unittest.TestCase):
    def test_pr_trigger_only_no_privileged_pull_request_target(self):
        self.assertRegex(WORKFLOW, r"(?m)^  pull_request:\s*$")
        self.assertIn("branches: [main]", WORKFLOW)
        self.assertNotIn("pull_request_target", WORKFLOW)

    def test_read_only_permissions_and_no_secrets(self):
        self.assertRegex(WORKFLOW, r"(?m)^permissions:\s*\n  contents: read\s*$")
        self.assertNotIn("contents: write", WORKFLOW)
        self.assertNotIn("secrets.", WORKFLOW)
        self.assertNotIn("github.token", WORKFLOW)
        self.assertIn("persist-credentials: false", WORKFLOW)

    def test_pinned_official_actions(self):
        self.assertRegex(WORKFLOW, r"actions/checkout@[a-f0-9]{40}")
        self.assertRegex(WORKFLOW, r"actions/setup-python@[a-f0-9]{40}")
        self.assertNotRegex(WORKFLOW, r"uses: [^\n]+@(main|master|v\d+)\s*$")

    def test_offline_only_no_live_reads_or_persistence(self):
        self.assertIn("python scripts/profile-job.test.py -v", WORKFLOW)
        self.assertIn("python -m py_compile scripts/*.py", WORKFLOW)
        self.assertNotIn("python scripts/profile-job.py\n", WORKFLOW)
        self.assertNotIn("python scripts/persist-state.py", WORKFLOW)
        self.assertNotIn("upload-artifact", WORKFLOW)
        self.assertNotIn("actions/cache", WORKFLOW)
        self.assertIn("timeout-minutes: 6", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
