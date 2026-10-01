import tempfile
import json
import unittest
from pathlib import Path

from app.services.computer_provider import ComputerProviderError
from app.services.docker_computer_provider import DockerComputerProvider


class FakeDockerCommand:
    def __init__(self):
        self.calls = []
        self.container = None

    def __call__(self, args, timeout):
        self.calls.append((tuple(args), timeout))
        if args[0] == "run":
            values = list(args)
            labels = [values[index + 1] for index, value in enumerate(values[:-1]) if value == "--label"]
            self.container = {
                "Id": "container-test",
                "Config": {
                    "Labels": {
                        "open-dots.bot-id": next(label.split("=", 1)[1] for label in labels if label.startswith("open-dots.bot-id=")),
                        "open-dots.computer-id": next(label.split("=", 1)[1] for label in labels if label.startswith("open-dots.computer-id=")),
                    },
                    "Env": [],
                },
                "State": {"Running": True, "Paused": False},
                "NetworkSettings": {"Ports": {"3000/tcp": [{"HostPort": "45678"}]}},
            }
            env_index = values.index("--env")
            while env_index < len(values) - 1:
                if values[env_index] == "--env":
                    self.container["Config"]["Env"].append(values[env_index + 1])
                    env_index += 2
                else:
                    env_index += 1
            # Mirror real docker: --env-file contents land in the container env.
            if "--env-file" in values:
                env_file = values[values.index("--env-file") + 1]
                with open(env_file) as handle:
                    for line in handle:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            self.container["Config"]["Env"].append(line)
            return "container-test"
        if args[0] == "inspect":
            if self.container is None:
                raise ComputerProviderError("No such container")
            return json.dumps(self.container)
        if args[0] == "port":
            return "127.0.0.1:45678"
        if args[0] == "rm":
            self.container = None
        return ""


class DockerComputerProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.docker = FakeDockerCommand()
        self.provider = DockerComputerProvider(
            image="open-dots-computer:test",
            workspace_root=self.root / "computers",
            seccomp_profile=self.root / "missing-seccomp.json",
            start_timeout=0.5,
            docker_command=self.docker,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_start_builds_a_restricted_per_bot_container(self):
        status = self.provider.get_or_create("bot-test")

        async def ready(_record):
            return {"status": "healthy", "width": 1280, "height": 720}

        self.provider._wait_until_ready = ready
        started = await self.provider.start(status.computer_id)

        self.assertEqual(started.state, "running")
        self.assertEqual(started.provider, "docker-playwright")
        self.assertTrue((self.root / "computers" / status.computer_id).is_dir())
        run_args = next(args for args, _timeout in self.docker.calls if args[0] == "run")
        self.assertEqual(run_args[0], "run")
        self.assertIn("--read-only", run_args)
        self.assertIn("--cap-drop", run_args)
        self.assertIn("ALL", run_args)
        self.assertIn("--security-opt", run_args)
        self.assertIn("no-new-privileges:true", run_args)
        self.assertNotIn("seccomp=", " ".join(run_args))
        self.assertIn("COMPUTER_COMMAND_TIMEOUT=30000", run_args)
        self.assertIn("--pids-limit", run_args)
        self.assertIn("--publish", run_args)
        self.assertIn("127.0.0.1::3000", run_args)
        self.assertNotIn("COMPUTER_TOKEN", started.to_dict())
        self.assertNotIn("token", started.to_dict())

    async def test_restart_recovers_and_controls_existing_container(self):
        first_provider = self.provider
        initial = first_provider.get_or_create("bot-restart")
        async def ready(_record):
            return {"status": "healthy"}

        first_provider._wait_until_ready = ready
        await first_provider.start(initial.computer_id)

        restarted = DockerComputerProvider(
            image="open-dots-computer:test",
            workspace_root=self.root / "computers",
            seccomp_profile=self.root / "missing-seccomp.json",
            docker_command=self.docker,
        )
        recovered = await restarted.reconcile("bot-restart")
        self.assertEqual(recovered.state, "running")
        stopped = await restarted.stop(recovered.computer_id)
        self.assertEqual(stopped.state, "stopped")
        self.assertIsNone(self.docker.container)

    async def test_recover_rejects_container_with_mismatched_computer_id_label(self):
        # Container names truncate the computer id to 70 chars, so a foreign
        # container can theoretically sit behind the expected name. Recovery
        # must not adopt it: its actions would otherwise run in another bot's
        # runtime.
        first_provider = self.provider
        initial = first_provider.get_or_create("bot-owner")
        async def ready(_record):
            return {"status": "healthy"}

        first_provider._wait_until_ready = ready
        await first_provider.start(initial.computer_id)

        # Simulate the collision: same name, but the label belongs to another bot.
        self.docker.container["Config"]["Labels"]["open-dots.computer-id"] = "computer-someone-else"

        restarted = DockerComputerProvider(
            image="open-dots-computer:test",
            workspace_root=self.root / "computers",
            seccomp_profile=self.root / "missing-seccomp.json",
            docker_command=self.docker,
        )
        recovered = await restarted.reconcile("bot-owner")
        self.assertEqual(recovered.state, "stopped")
        self.assertIsNone(restarted._runtimes.get(recovered.computer_id))
        # The foreign container is left untouched, never adopted.
        self.assertIsNotNone(self.docker.container)

    async def test_browser_terminal_files_input_and_screenshot_use_scoped_runtime(self):
        status = self.provider.get_or_create("bot-test")

        async def ready(_record):
            return {"status": "healthy"}

        async def request(_record, method, route, payload=None):
            if route == "/health":
                return {"status": "healthy"}
            if route == "/navigate":
                return {"url": payload["url"], "title": "Example"}
            if route == "/terminal":
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}
            if route == "/files":
                return {"path": payload["path"], "entries": []}
            if route == "/input":
                return {"accepted": True, "type": payload["event"]["type"]}
            if route == "/screenshot":
                return {
                    "frame_id": "frame-real-1",
                    "format": "jpeg",
                    "width": 1280,
                    "height": 720,
                    "data": "base64-jpeg",
                }
            raise AssertionError(route)

        self.provider._wait_until_ready = ready
        self.provider._request = request
        await self.provider.start(status.computer_id)

        navigated = await self.provider.browser_navigate(status.computer_id, "https://example.test")
        self.assertEqual(navigated["title"], "Example")
        terminal = await self.provider.terminal_execute(status.computer_id, "printf safe")
        self.assertEqual(terminal["stdout"], "ok")
        files = await self.provider.files_list(status.computer_id, "/workspace")
        self.assertEqual(files["entries"], [])
        input_result = await self.provider.send_input(
            status.computer_id,
            {"type": "click", "x": 4, "y": 5},
        )
        self.assertTrue(input_result["accepted"])
        screen = await self.provider.screenshot(status.computer_id)
        self.assertTrue(screen["available"])
        self.assertEqual(screen["frame_id"], "frame-real-1")
        self.assertEqual(self.provider.describe("bot-test").frame_id, "frame-real-1")

    async def test_docker_failure_is_reported_and_marks_runtime_unhealthy(self):
        def failing_docker(_args, _timeout):
            raise ComputerProviderError("Docker daemon is unavailable.")

        provider = DockerComputerProvider(
            workspace_root=self.root / "computers",
            docker_command=failing_docker,
        )
        status = provider.get_or_create("bot-test")
        with self.assertRaisesRegex(ComputerProviderError, "daemon is unavailable"):
            await provider.start(status.computer_id)
        self.assertEqual(provider.describe("bot-test").state, "error")
        self.assertEqual(provider.describe("bot-test").health, "unhealthy")


if __name__ == "__main__":
    unittest.main()
