"""Explicit backend action definitions and chat command parsing."""

from typing import Optional

from app.services.action_gateway import ActionDefinition, ActionInvocation, action_gateway
from app.services.cohesivity_service import (
    VALID_RESOURCES,
    BackendServiceError,
    cohesivity_service,
)


class BackendCommandError(ValueError):
    """Raised when an explicit backend command is malformed."""


def parse_backend_command(prompt: str) -> Optional[ActionInvocation]:
    """Parse the explicit backend command.

    Supported forms:
      /backend setup
      /backend status
      /backend provision <resource>
    """

    text = (prompt or "").strip()
    if not text.lower().startswith("/backend"):
        return None

    first_line = text.split("\n", 1)[0]
    parts = first_line.split()
    if parts[0].lower() != "/backend":
        return None

    if len(parts) < 2:
        raise BackendCommandError(
            "Use /backend setup, /backend status, or /backend provision <resource>."
        )

    subcommand = parts[1].lower()

    if subcommand == "setup":
        return ActionInvocation(
            name="backend.setup",
            arguments={},
            target={"provider": "cohesivity"},
            preview="Create a new Cohesivity tenant",
        )

    if subcommand == "status":
        return ActionInvocation(
            name="backend.status",
            arguments={},
            target={"provider": "cohesivity"},
            preview="Check Cohesivity tenant status",
        )

    if subcommand == "provision":
        if len(parts) < 3:
            raise BackendCommandError(
                f"Specify a resource to provision. "
                f"Valid resources: {', '.join(sorted(VALID_RESOURCES))}"
            )
        resource = parts[2].lower()
        if resource not in VALID_RESOURCES:
            raise BackendCommandError(
                f"Unknown resource: {resource}. "
                f"Valid resources: {', '.join(sorted(VALID_RESOURCES))}"
            )
        return ActionInvocation(
            name="backend.provision",
            arguments={"resource": resource},
            target={"provider": "cohesivity"},
            preview=f"Provision {resource} on Cohesivity",
        )

    raise BackendCommandError(
        "Use /backend setup, /backend status, or /backend provision <resource>."
    )


async def execute_backend_setup(call: ActionInvocation):
    return await cohesivity_service.create_tenant()


async def execute_backend_status(call: ActionInvocation):
    return await cohesivity_service.get_status()


async def execute_backend_provision(call: ActionInvocation):
    try:
        return await cohesivity_service.provision_resource(
            resource=call.arguments["resource"],
        )
    except (KeyError, TypeError) as exc:
        raise BackendServiceError("The backend provision arguments are invalid.") from exc


action_gateway.register_action(
    ActionDefinition(
        name="backend.setup",
        tool="backend",
        action="setup",
        intent="Create a new Cohesivity tenant for backend infrastructure.",
        risk="external",
        requires_approval=True,
    ),
    execute_backend_setup,
)

action_gateway.register_action(
    ActionDefinition(
        name="backend.status",
        tool="backend",
        action="status",
        intent="Check the status of a Cohesivity tenant.",
        risk="external",
        requires_approval=False,
    ),
    execute_backend_status,
)

action_gateway.register_action(
    ActionDefinition(
        name="backend.provision",
        tool="backend",
        action="provision",
        intent="Provision a resource on the Cohesivity backend.",
        risk="external",
        requires_approval=True,
    ),
    execute_backend_provision,
)
