import unittest

from app.services.cohesivity_actions import BackendCommandError, parse_backend_command


class BackendParserValidTests(unittest.TestCase):
    def test_setup_returns_correct_invocation(self):
        call = parse_backend_command("/backend setup")

        self.assertEqual(call.name, "backend.setup")
        self.assertEqual(call.arguments, {})
        self.assertEqual(call.target, {"provider": "cohesivity"})
        self.assertIn("tenant", call.preview.lower())

    def test_status_returns_correct_invocation(self):
        call = parse_backend_command("/backend status")

        self.assertEqual(call.name, "backend.status")
        self.assertEqual(call.arguments, {})
        self.assertEqual(call.target, {"provider": "cohesivity"})

    def test_provision_returns_resource_in_arguments(self):
        call = parse_backend_command("/backend provision postgres")

        self.assertEqual(call.name, "backend.provision")
        self.assertEqual(call.arguments, {"resource": "postgres"})
        self.assertEqual(call.target, {"provider": "cohesivity"})
        self.assertIn("postgres", call.preview.lower())

    def test_command_is_case_insensitive(self):
        call = parse_backend_command("/Backend Setup")
        self.assertEqual(call.name, "backend.setup")

        call = parse_backend_command("/BACKEND PROVISION Postgres")
        self.assertEqual(call.arguments, {"resource": "postgres"})

    def test_extra_whitespace_is_tolerated(self):
        call = parse_backend_command("  /backend   status  ")
        self.assertEqual(call.name, "backend.status")


class BackendParserInvalidTests(unittest.TestCase):
    def test_missing_subcommand_raises(self):
        with self.assertRaises(BackendCommandError):
            parse_backend_command("/backend")

    def test_missing_subcommand_whitespace_only_raises(self):
        with self.assertRaises(BackendCommandError):
            parse_backend_command("/backend   ")

    def test_unknown_subcommand_raises(self):
        with self.assertRaises(BackendCommandError):
            parse_backend_command("/backend deploy")

    def test_provision_without_resource_raises(self):
        with self.assertRaises(BackendCommandError):
            parse_backend_command("/backend provision")

    def test_provision_with_invalid_resource_raises(self):
        with self.assertRaises(BackendCommandError):
            parse_backend_command("/backend provision unicorndb")


class BackendParserNonMatchTests(unittest.TestCase):
    def test_plain_message_returns_none(self):
        self.assertIsNone(parse_backend_command("what is cohesivity"))

    def test_similar_prefix_returns_none(self):
        self.assertIsNone(parse_backend_command("/backendstatus"))

    def test_empty_and_none_return_none(self):
        self.assertIsNone(parse_backend_command(""))
        self.assertIsNone(parse_backend_command(None))


if __name__ == "__main__":
    unittest.main()
