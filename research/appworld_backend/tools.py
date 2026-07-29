"""
AppWorld tool executor for the Halluci-Action pipeline (IN-PROCESS execution).

This module is the AppWorld analogue of ``research/tools/odoo_tools.py``. Instead of
talking to Odoo over JSON-RPC, it drives an AppWorld ``world`` object *in the same
process* by calling ``world.apis.<app>.<api>(**params)`` directly (NO MCP, NO server,
NO ``world.execute``).

Key responsibilities (mirroring OdooToolExecutor):
  1. ``execute(tool_name, params)``   -> dispatch a single tool call.
  2. ``build_tool_schemas(kl, ...)``  -> OpenAI/Anthropic tool schemas derived from
     AppWorld's ``api_docs.function_calling()``, filtered to a hand-listed set, with
     optional ``constraints`` + KL1/2/3 rendering (mirrors ToolSpec.description(kl)).
  3. Login / access-token handling. AppWorld apps are OAuth-style: an authenticated
     API needs an ``access_token`` obtained via ``apis.<app>.login(username, password)``.
     Credentials come from the Supervisor app. We inject the token automatically so the
     agent never has to see or supply it.

Tool names follow AppWorld's function-calling convention ``"<app>__<api>"`` (the "__"
separator is confirmed from ``collections/api_docs.py::function_calling`` and
``AppWorldInitDefaults.direct_function_separator``).
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any

try:  # pragma: no cover - logging convenience only
    import structlog

    logger = structlog.get_logger(__name__)
except ModuleNotFoundError:  # pragma: no cover
    logger = logging.getLogger(__name__)


# AppWorld's function_calling() names apps + apis as "<app>__<api>".
APP_API_SEPARATOR = "__"

# APIs that establish identity and therefore must NOT receive an injected access_token.
PUBLIC_API_NAMES = {
    "login",
    "signup",
    "send_verification_code",
    "verify_account",
    "send_password_reset_code",
    "reset_password",
}

# Auth parameters that AppWorld's function_calling docs expose but which we inject
# automatically. They are stripped from the schema shown to the agent.
AUTO_INJECTED_PARAMS = ("access_token",)


def _jsonable(value: Any) -> Any:
    """Coerce an AppWorld response (Munch/dict/list/scalar) into plain JSON types."""
    return json.loads(json.dumps(value, default=str))


class AppWorldToolExecutor:
    def __init__(
        self,
        world: Any,
        exposed_apis: list[str],
        constraints: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        """
        Parameters
        ----------
        world:
            A constructed ``appworld.AppWorld`` instance (in-process).
        exposed_apis:
            The hand-listed set of "<app>__<api>" tool names to expose (see
            ``EXPOSED_APIS`` in ``run_appworld_poc.py``). Filtering is essential:
            AppWorld ships hundreds of APIs and we must not dump them all.
        constraints:
            Optional per-tool constraint strings keyed by "<app>__<api>", surfaced in
            the tool description at KL1 (mirrors ToolSpec.constraints).
        """
        self.world = world
        self.exposed_apis = list(exposed_apis)
        self.constraints = dict(constraints or {})
        # tool names the agent called that were NOT in exposed_apis (recorded, not blocked)
        self.out_of_exposure: list[str] = []

        # Cached credentials / tokens (populated lazily on first authed call).
        self._username: str | None = None
        self._account_passwords: dict[str, str] | None = None
        self._token_cache: dict[str, str] = {}

        # Cached {tool_name: function_calling doc}.
        self._doc_by_name: dict[str, dict[str, Any]] | None = None

    # ------------------------------------------------------------------ #
    # AppWorld api-docs access
    # ------------------------------------------------------------------ #
    def _all_function_docs(self) -> dict[str, dict[str, Any]]:
        if self._doc_by_name is None:
            # world.task.api_docs.function_calling() -> list of
            #   {"type": "function", "function": {"name": "app__api", "description": ...,
            #    "parameters": {json schema}}}
            docs = self.world.task.api_docs.function_calling()
            self._doc_by_name = {doc["function"]["name"]: doc for doc in docs}
        return self._doc_by_name

    def _api_declares_access_token(self, tool_name: str) -> bool:
        """True if the API's own schema lists ``access_token`` as a parameter.

        AppWorld runs with ``raise_on_extra_parameters=True`` by default, so we must
        only inject ``access_token`` for APIs that actually accept it.
        """
        doc = self._all_function_docs().get(tool_name)
        if not doc:
            return False
        props = doc["function"].get("parameters", {}).get("properties", {})
        return "access_token" in props

    # ------------------------------------------------------------------ #
    # Login / access-token helper
    # ------------------------------------------------------------------ #
    def _ensure_credentials(self) -> None:
        """Load the supervisor username + per-app account passwords (once).

        The supervisor app auto-authenticates the main user for in-process calls, so
        ``show_profile`` / ``show_account_passwords`` need no token (confirmed from
        appworld tests: ``world.apis.supervisor.show_account_passwords()``).
        """
        if self._account_passwords is not None:
            return
        profile = self.world.apis.supervisor.show_profile()
        self._username = profile["email"]
        # The `phone` app's login takes the account PHONE NUMBER as username, every other
        # app takes the email (verified via api_docs.show_api_doc(<app>, "login")). Using
        # the email for phone made every phone__* call fail 401 "Invalid credentials".
        self._phone_username = profile.get("phone_number")
        self._account_passwords = {
            row["account_name"]: row["password"]
            for row in self.world.apis.supervisor.show_account_passwords()
        }

    def _login_username(self, app_name: str) -> str | None:
        """Username to log into ``app_name`` with (phone -> phone_number, else email)."""
        if app_name == "phone" and getattr(self, "_phone_username", None):
            return self._phone_username
        return self._username

    def access_token(self, app_name: str) -> str | None:
        """Return (and cache) an access token for ``app_name``, or None if the
        supervisor has no account on that app."""
        if app_name in self._token_cache:
            return self._token_cache[app_name]
        self._ensure_credentials()
        assert self._account_passwords is not None  # for type checkers
        password = self._account_passwords.get(app_name)
        if password is None:
            return None
        app_apis = getattr(self.world.apis, app_name)
        # AppWorld login: apis.<app>.login(username=<email|phone_number>, password=<pw>)
        result = app_apis.login(username=self._login_username(app_name), password=password)
        token = result["access_token"] if isinstance(result, dict) else result
        self._token_cache[app_name] = token
        return token

    # ------------------------------------------------------------------ #
    # Dispatch (mirrors OdooToolExecutor.execute)
    # ------------------------------------------------------------------ #
    def execute(self, tool_name: str, parameters: dict[str, Any]) -> Any:
        """Dispatch a single tool call and return a JSON-able result.

        Resolution order (mirrors OdooToolExecutor: ``getattr(self, tool_name)``):
          1. An explicit wrapper method named exactly ``<app>__<api>`` (e.g. the
             return-structure-trap wrapper below), if defined.
          2. Otherwise, a generic passthrough that calls the AppWorld api directly.
        """
        parameters = dict(parameters or {})
        # OBSERVE, don't restrict: if the agent called a tool we never exposed, record it
        # (it inferred a valid AppWorld name on its own — a tool-hallucination signal) but
        # still execute. Blocking would manufacture a fake failure, which is exactly the
        # class of artefact (max_steps truncation, 401s) that pollutes the HA metric.
        if tool_name not in set(self.exposed_apis):
            self.out_of_exposure.append(tool_name)
            logger.warning("out-of-exposure tool call (executed anyway): %s", tool_name)
        handler = getattr(self, tool_name, None)
        if callable(handler):
            result = handler(**parameters)
        else:
            result = self._call_api(tool_name, parameters)
        return _jsonable(result)

    def _call_api(self, tool_name: str, parameters: dict[str, Any]) -> Any:
        """Generic in-process passthrough: world.apis.<app>.<api>(**params)."""
        if APP_API_SEPARATOR not in tool_name:
            raise ValueError(
                f"Tool name '{tool_name}' is not of the form '<app>{APP_API_SEPARATOR}<api>'."
            )
        app_name, api_name = tool_name.split(APP_API_SEPARATOR, 1)
        call_params = dict(parameters)
        # Auto-inject access_token for authenticated APIs (never shown to the agent).
        if api_name not in PUBLIC_API_NAMES and self._api_declares_access_token(tool_name):
            token = self.access_token(app_name)
            if token is not None:
                call_params.setdefault("access_token", token)
        api = getattr(getattr(self.world.apis, app_name), api_name)
        # IMPORTANT: direct in-process call. We never use world.execute for actions.
        return api(**call_params)

    # ------------------------------------------------------------------ #
    # Example wrapper methods
    # ------------------------------------------------------------------ #
    # NOTE: These are EXAMPLES. Wrapper methods are named exactly "<app>__<api>" so the
    # dispatch in execute() picks them up. Delete/adapt to whatever your task needs.

    def venmo__show_venmo_balance(self, **params: Any) -> dict[str, Any]:
        """RETURN-STRUCTURE TRAP (example).

        The multi-field return shape is the hallucination trap: when a tool returns
        several related figures (total vs. available vs. pending), the agent may cite
        the wrong one in its post-action claim (an Over-claim / mis-attribution). We
        expose all three deliberately so the judge can catch that.

        The exact field names below are illustrative; align them with the real
        VenmoBalanceResponse fields for your data snapshot (see TODO).
        """
        raw = self._call_api("venmo__show_venmo_balance", params)
        data = raw if isinstance(raw, dict) else {"balance": raw}
        total = data.get("balance", data.get("total"))
        # TODO: replace these best-effort derivations with the real response fields.
        pending = data.get("pending_balance", data.get("pending", 0))
        available = data.get("available_balance", data.get("available", total))
        return {
            "total": total,        # full Venmo balance
            "pending": pending,    # not yet cleared
            "available": available,  # spendable right now
            "_raw": data,          # keep the raw payload for transparency
        }

    def spotify__show_playlist_library(self, **params: Any) -> Any:
        """Plain example wrapper (no reshaping) - shows the passthrough pattern."""
        return self._call_api("spotify__show_playlist_library", params)

    # ------------------------------------------------------------------ #
    # Tool-schema builder (api_docs.function_calling() + constraints + KL)
    # ------------------------------------------------------------------ #
    def build_tool_schemas(
        self, knowledge_level: str = "KL1", provider: str = "openai"
    ) -> list[dict[str, Any]]:
        """Build provider-specific tool schemas for ``self.exposed_apis``.

        Starts from AppWorld's ``function_calling()`` docs (already OpenAI-shaped),
        FILTERS to the hand-listed EXPOSED_APIS, strips auto-injected auth params, and
        re-renders the description per knowledge level (KL1/2/3) with optional
        constraints (mirrors ToolSpec.to_openai_tool / to_anthropic_tool).
        """
        docs = self._all_function_docs()
        schemas: list[dict[str, Any]] = []
        for tool_name in self.exposed_apis:
            doc = docs.get(tool_name)
            if doc is None:
                # TODO(user): tool_name is not a valid function_calling name for this
                # task's allowed_apps. Check spelling / that the app is enabled.
                logger.warning("unknown exposed api (skipped): %s", tool_name)
                continue
            function = deepcopy(doc["function"])
            parameters = function.setdefault(
                "parameters", {"type": "object", "properties": {}}
            )
            properties = parameters.setdefault("properties", {})
            for auth_param in AUTO_INJECTED_PARAMS:
                properties.pop(auth_param, None)
            if "required" in parameters:
                parameters["required"] = [
                    name for name in parameters["required"] if name not in AUTO_INJECTED_PARAMS
                ]
            function["description"] = self._render_description(
                tool_name, function.get("description", ""), knowledge_level
            )
            if provider == "openai":
                schemas.append({"type": "function", "function": function})
            elif provider in ("anthropic", "claude"):
                schemas.append(
                    {
                        "name": function["name"],
                        "description": function["description"],
                        "input_schema": parameters,
                    }
                )
            else:
                raise ValueError(f"Unsupported provider: {provider}")
        return schemas

    def _render_description(
        self, tool_name: str, base_description: str, knowledge_level: str
    ) -> str:
        """KL1/2/3 rendering hook, mirroring ToolSpec.description(knowledge_level).

        KL1: full description + explicit constraints (most guidance).
        KL2: full description only (agent infers constraints).
        KL3: minimal (first sentence only; agent relies on prior knowledge).
        """
        level = knowledge_level.upper()
        constraints = tuple(self.constraints.get(tool_name, ()))
        base = (base_description or "").strip()
        if level == "KL1":
            if constraints:
                return f"{base} Important constraints: {' '.join(constraints)}"
            return base
        if level == "KL2":
            return base
        if level == "KL3":
            first_sentence = base.split(". ")[0].strip()
            if not first_sentence:
                return base
            return first_sentence if first_sentence.endswith(".") else first_sentence + "."
        raise ValueError(f"Unsupported knowledge level: {knowledge_level}")
