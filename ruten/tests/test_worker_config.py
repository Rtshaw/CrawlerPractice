import json
import os
import subprocess
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


class WorkerComposeTests(unittest.TestCase):
    def test_worker_compose_enforces_disposable_non_root_runtime(self):
        environment = os.environ.copy()
        environment.update(
            {
                "OTP_SERVER_URL": "https://otp.invalid",
                "OTP_CONSUMER_TOKEN": "test-token-not-a-secret",
            }
        )
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "docker/compose.worker.yml",
                "config",
                "--format",
                "json",
            ],
            cwd=PROJECT_DIR,
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        service = json.loads(result.stdout)["services"]["fee-worker"]
        self.assertEqual(service["build"]["dockerfile"], "docker/Dockerfile.worker")
        self.assertEqual(service["user"], "10001:10001")
        self.assertTrue(service["read_only"])
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertNotIn("restart", service)
        self.assertEqual(service["environment"]["OTP_SERVER_URL"], "https://otp.invalid")
        self.assertEqual(service["environment"]["OTP_CONSUMER_TOKEN"], "test-token-not-a-secret")

        volumes = {volume["target"]: volume for volume in service["volumes"]}
        self.assertTrue(volumes["/app/config.ini"]["read_only"])
        self.assertTrue(volumes["/app/cookies.json"]["read_only"])
        self.assertFalse(volumes["/runtime/logs"].get("read_only", False))
        self.assertFalse(volumes["/runtime/state"].get("read_only", False))

    def test_worker_can_execute_uc_driver_from_ephemeral_home(self):
        smoke_script = PROJECT_DIR / "tests" / "uc_browser_smoke.py"
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                "docker/worker.env.example",
                "-f",
                "docker/compose.worker.yml",
                "run",
                "--rm",
                "--no-deps",
                "--volume",
                f"{smoke_script}:/test/uc_browser_smoke.py:ro",
                "--entrypoint",
                "python",
                "fee-worker",
                "/test/uc_browser_smoke.py",
            ],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("UC_BROWSER_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
