"""Explicit web search action definitions and chat command parsing."""

from typing import Optional

from app.services.action_gateway import ActionDefinition, ActionInvocation, action_gateway
from app.services.serply_service import serply_service
from app.services.youcom_service import (
    MAX_QUERY_CHARS,
    SearchServiceError,
    youcom_service,
)


class SearchCommandError(ValueError):
    """Raised when an explicit web search command is malformed."""


def search_provider() -> str:
    """Use Serply when its key is configured, otherwise You.com."""
    return "serply" if serply_service.get_api_key() else "youcom"


def parse_search_command(prompt: str) -> Optional[ActionInvocation]:
    """Parse the explicit web search command.

    Supported form:
      /search <query>
    """

    text = (prompt or "").strip()
    if not text.lower().startswith("/search"):
        return None

    first_line = text.split("\n", 1)[0]
    parts = first_line.split(None, 1)
    if parts[0].lower() != "/search":
        return None

    query = parts[1].strip() if len(parts) == 2 else ""
    if not query:
        raise SearchCommandError("Add a query after /search, like /search latest fastapi release notes.")
    if len(query) > MAX_QUERY_CHARS:
        raise SearchCommandError(f"A search query must be at most {MAX_QUERY_CHARS} characters.")

    return ActionInvocation(
        name="search.web",
        arguments={"query": query, "count": 5},
        target={"provider": search_provider()},
        preview=f'Web search for "{query[:80]}"',
    )


async def execute_web_search(call: ActionInvocation):
    provider = call.target.get("provider")
    service = serply_service if provider == "serply" else youcom_service
    try:
        return await service.search_web(
            query=call.arguments["query"],
            count=call.arguments.get("count", 5),
        )
    except (KeyError, TypeError) as exc:
        raise SearchServiceError("The web search action arguments are invalid.") from exc


action_gateway.register_action(
    ActionDefinition(
        name="search.web",
        tool="search",
        action="web",
        intent="Search the web for current information through You.com, or Serply when SERPLY_API_KEY is set.",
        risk="external",
        requires_approval=False,
    ),
    execute_web_search,
)