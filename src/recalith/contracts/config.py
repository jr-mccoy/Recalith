"""Project and provider configuration with SYSTEM_SPEC defaults.

Values here are initial engineering defaults (SYSTEM_SPEC §6.3, §8.2, §11),
configurable per installation. Retention values record whether they are the
release profile's default or an explicit operator override, so a profile
transition can change defaults without discarding overrides (§10.1).
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import Digest, Id, One, PortablePath, Revision, StrictModel, UtcTime

KIB = 1024
ReleaseProfile = Literal["claude_preview", "full"]
DomainProfile = Literal["coding", "general"]
PositiveInt = Annotated[int, Field(gt=0)]

# --------------------------------------------------------------------------
# Hard limits shared with the fast path (stdlib mirrors these numbers).

EVENT_PAYLOAD_CAP = 64 * KIB
SEGMENT_CAP = 256 * KIB
MODEL_INPUT_CAP = 96 * KIB
WIRE_STDOUT_CAP = 256 * KIB
STDERR_CAP = 64 * KIB
RESULT_TEXT_HEAD = 8 * KIB
RESULT_TEXT_TAIL = 8 * KIB
ERROR_SIGNATURE_CAP = 1 * KIB
EXTENSIONS_CAP = 4 * KIB
HOOK_SOFT_DEADLINE_MS = 250
SESSION_LOCK_WAIT_MS = 20
SESSION_SCRATCH_CAP = 128 * KIB
SESSION_SCRATCH_ENTRIES = 256
SESSION_SCRATCH_OUTCOMES = 32
HOOK_DEPENDENCY_FILES = 16
HOOK_DEPENDENCY_BYTES = 1024 * KIB
HOOK_DEPENDENCY_MS = 50
FALLBACK_ROWS = 32
REVIEW_BATCH_MAX_CANDIDATES = 8
ASSESSMENT_OP_MAX_BYTES = 768
REVIEW_ENVELOPE_BYTES = 2000
OBJECTION_MAX_BYTES = 160
TOOL_ASSERTION_IDENTITY_MAX = 256
TOOL_ASSERTION_VALUE_MAX = 4 * KIB
TOOL_ASSERTIONS_MAX = 32
FAILURE_DEBOUNCE_EVENTS = 6
FAILURE_DEBOUNCE_SECONDS = 600
DEFAULT_PIVOT_PREFIXES = ("new task:", "switch task:", "separate task:")
CODE_CLUSTER_COMPONENTS = ("src", "test", "tests", "docs")

# Model purposes, output allowances and decoded-body caps (SYSTEM_SPEC §6.3).
ModelPurpose = Literal["update_task", "build_episode", "extract_claims", "review_claims", "revalidate"]
PURPOSE_OUTPUT_ALLOWANCE: dict[str, int] = {
    "update_task": 1500,
    "build_episode": 8000,
    "extract_claims": 8000,
    "review_claims": 3000,
    "revalidate": 3000,
}
PROTECTED_PURPOSES = frozenset({"review_claims", "revalidate"})
# A thinking model's reasoning counts against the provider's hard output cap
# (decision 0027 item 9), so the cap sent and reserved is the allowance plus
# this headroom; the decoded-body cap stays 3 × the allowance (decision 0029).
REASONING_HEADROOM = 6000


def body_cap_for(purpose: str) -> int:
    """Decoded logical JSON body cap: 3 × the purpose's output allowance."""
    return 3 * PURPOSE_OUTPUT_ALLOWANCE[purpose]


def provider_output_cap(purpose: str) -> int:
    """The provider's hard output cap and the reserved output estimate: the allowance plus the reasoning headroom."""
    return PURPOSE_OUTPUT_ALLOWANCE[purpose] + REASONING_HEADROOM


def estimate_tokens(utf8_bytes: int) -> int:
    """The labeled local estimate: ceil(UTF-8 bytes / 3)."""
    return -(-utf8_bytes // 3)


# --------------------------------------------------------------------------
# Configuration models


class BudgetConfig(StrictModel):
    daily_invocations: PositiveInt = 90
    daily_input_estimate: PositiveInt = 1_800_000  # ordinary 1,500,000: the invocation cap binds first at live request sizes (decision 0034)
    daily_output_estimate: PositiveInt = 180_000
    protected_invocations: PositiveInt = 30
    protected_input_estimate: PositiveInt = 300_000
    protected_output_estimate: PositiveInt = 60_000
    concurrent_requests: One = 1
    timeout_seconds: PositiveInt = 120
    evidence_expansion_rounds: Annotated[int, Field(ge=0, le=2)] = 2
    retry_backoff_seconds: list[PositiveInt] = Field(default_factory=lambda: [60, 300, 1800])
    episode_target_input_estimate: PositiveInt = 8000

    @model_validator(mode="after")
    def _protected_within_total(self) -> "BudgetConfig":
        if (
            self.protected_invocations > self.daily_invocations
            or self.protected_input_estimate > self.daily_input_estimate
            or self.protected_output_estimate > self.daily_output_estimate
        ):
            raise ValueError("protected reserve cannot exceed the daily totals")
        return self


class ContextBudgetConfig(StrictModel):
    session_start: PositiveInt = 2000
    prompt: PositiveInt = 1000
    pre_action: PositiveInt = 400
    unchanged_session_total: PositiveInt = 4000
    compaction_restore: PositiveInt = 2000
    pre_action_substitution: PositiveInt = 400


class RetentionValue(StrictModel):
    days: PositiveInt
    source: Literal["profile_default", "operator_override"] = "profile_default"


def _days(n: int) -> RetentionValue:
    return RetentionValue(days=n)


PROFILE_UNPINNED_EVENT_DAYS = {"claude_preview": 180, "full": 30}


class RetentionConfig(StrictModel):
    unpinned_event_payload: RetentionValue = Field(default_factory=lambda: _days(180))
    episode_after_closure: RetentionValue = Field(default_factory=lambda: _days(180))
    closed_task_history: RetentionValue = Field(default_factory=lambda: _days(90))
    proposal_diagnostics: RetentionValue = Field(default_factory=lambda: _days(7))
    delivery_metadata: RetentionValue = Field(default_factory=lambda: _days(90))
    private_backups: RetentionValue = Field(default_factory=lambda: _days(30))


class WorkerConfig(StrictModel):
    mode: Literal["persistent", "session"] = "persistent"
    active_poll_seconds: PositiveInt = 1
    idle_poll_seconds: PositiveInt = 5
    session_idle_exit_minutes: PositiveInt = 10
    paused_task_hours: PositiveInt = 24
    volatile_review_days: PositiveInt = 30
    stable_review_days: PositiveInt = 180
    consolidation_episode_count: PositiveInt = 20
    consolidation_hours: PositiveInt = 24


class SegmentationConfig(StrictModel):
    pivot_prefixes: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(default_factory=lambda: list(DEFAULT_PIVOT_PREFIXES))
    disjoint_action_count: PositiveInt = 5
    idle_boundary_minutes: PositiveInt = 30
    continuity_path_actions: PositiveInt = 3
    continuity_pause_hours: PositiveInt = 24
    cluster_mappings: dict[PortablePath, Annotated[str, Field(pattern=r"^@[a-z0-9_]+$")]] = Field(default_factory=dict)


class ProjectConfig(StrictModel):
    config_schema: One = 1
    project_id: Id
    domain_profile: DomainProfile = "coding"
    release_profile: ReleaseProfile = "claude_preview"
    policy_revision: Revision = 1
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    context: ContextBudgetConfig = Field(default_factory=ContextBudgetConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    segmentation: SegmentationConfig = Field(default_factory=SegmentationConfig)
    runtime_versions: dict[Literal["python_version", "node_version"], Annotated[str, Field(max_length=64)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _profile_defaults(self) -> "ProjectConfig":
        unpinned = self.retention.unpinned_event_payload
        if unpinned.source == "profile_default" and unpinned.days != PROFILE_UNPINNED_EVENT_DAYS[self.release_profile]:
            raise ValueError("unpinned event retention marked as profile default does not match the release profile")
        if self.release_profile == "claude_preview" and self.worker.mode != "persistent":
            raise ValueError("session worker mode is a full-release capability")
        return self

    @classmethod
    def defaults_for(cls, project_id: str, *, release_profile: ReleaseProfile = "claude_preview", domain_profile: DomainProfile = "coding") -> "ProjectConfig":
        retention = RetentionConfig(unpinned_event_payload=_days(PROFILE_UNPINNED_EVENT_DAYS[release_profile]))
        idle = 5 if release_profile == "claude_preview" else 30
        return cls(
            project_id=project_id,
            release_profile=release_profile,
            domain_profile=domain_profile,
            retention=retention,
            worker=WorkerConfig(idle_poll_seconds=idle),
        )


AuthRouteKind = Literal["env_api_key", "env_oauth_token", "env_cloud", "api_key_helper", "none"]
EnvKeyName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")]
# Names an explicit route or nonsecret switch may never use (SYSTEM_SPEC §9.1, §13.1).
FORBIDDEN_ENV_NAMES = frozenset({"CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION"})
_CREDENTIAL_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.I)
ModelName = Annotated[str, Field(min_length=1, max_length=128)]
CheckName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]

# Decision 0023: direct-API backends are adapters Recalith ships; process backends launch a configured executable.
PROCESS_BACKENDS = frozenset({"claude_cli", "json_process"})
API_BACKENDS = frozenset({"anthropic_messages", "openai_compatible"})
BACKEND_DIALECT = {"anthropic_messages": "messages", "openai_compatible": "chat_completions"}
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _forbidden_env_name(name: str) -> bool:
    return name.upper().startswith("RECALITH_") or name.upper() in FORBIDDEN_ENV_NAMES


def url_host(url: str) -> str | None:
    from urllib.parse import urlsplit

    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def is_loopback_url(url: str) -> bool:
    return (url_host(url) or "").lower() in LOOPBACK_HOSTS


class ApiEndpoint(StrictModel):
    """Where and how a direct-API backend sends its one request (decision 0023).

    ``url`` is the full resource URL the engine POSTs to: ``https``, or
    ``http`` only for a loopback host (a local server). It carries no user
    information, no fragment and no credential-shaped query; the key travels
    only in ``auth_header``, read from the environment by name in the child.
    ``output_cap_field`` names the request field that carries the hard output
    limit and ``json_mode`` the native JSON mode (Chat Completions only);
    ``api_version`` is the ``anthropic-version`` header (Messages only).
    """

    url: Annotated[str, Field(min_length=10, max_length=2048)]
    dialect: Literal["messages", "chat_completions"]
    auth_header: Literal["x-api-key", "authorization_bearer", "api-key", "none"]
    output_cap_field: Literal["max_tokens", "max_completion_tokens"]
    json_mode: Literal["none", "json_object"]
    api_version: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")] | None = None

    @model_validator(mode="after")
    def _safe_endpoint(self) -> "ApiEndpoint":
        from urllib.parse import parse_qsl, urlsplit

        from recalith.fast import redact

        if any(ord(c) < 33 or ord(c) == 127 for c in self.url):
            raise ValueError("the endpoint URL contains whitespace or control characters")
        try:
            parts = urlsplit(self.url)
            parts.port  # noqa: B018 - raises on an invalid port
        except ValueError:
            raise ValueError("the endpoint URL is not a valid URL") from None
        if parts.scheme not in ("https", "http") or not parts.hostname:
            raise ValueError("the endpoint URL must be https://host/path (http only for a loopback host)")
        if parts.scheme == "http" and parts.hostname.lower() not in LOOPBACK_HOSTS:
            raise ValueError("plain http is allowed only to a loopback host (127.0.0.1, ::1, localhost)")
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            raise ValueError("the endpoint URL may not carry user information")
        if parts.fragment or "#" in self.url:
            raise ValueError("the endpoint URL may not carry a fragment")
        for name, value in parse_qsl(parts.query, keep_blank_values=True):
            if _CREDENTIAL_NAME.search(name) or redact.contains_secret(value):
                raise ValueError("the endpoint URL may not carry a credential; keys travel only in the auth header")
        if self.dialect == "messages":
            if self.auth_header not in ("x-api-key", "authorization_bearer") or self.output_cap_field != "max_tokens" or self.json_mode != "none" or self.api_version is None:
                raise ValueError("the messages dialect uses x-api-key or bearer auth, max_tokens, no native JSON mode, and an api_version")
        elif self.api_version is not None:
            raise ValueError("api_version is the messages dialect's anthropic-version header")
        return self


class ProviderCertification(StrictModel):
    """What a successful probe of this exact route observed (Task 0 / Task 7; decision 0023).

    ``certified`` is true only for a complete *live* observation with the
    operator's checked background-use eligibility (``not_applicable_local``
    only for a loopback API endpoint, checked by ``ProviderConfig``). The
    route is usable only while the launched program's digest (the CLI
    executable, or the shipped API adapter sources), host version, auth route,
    invocation and, for an API route, the resolved model still equal what was
    certified; any change requires recertification. ``failed_checks`` lists
    what a non-passing probe run failed.
    """

    certified: bool
    certified_at: UtcTime | None = None
    host_version: Annotated[str, Field(max_length=128)] | None = None
    report_digest: Digest | None = None
    executable_sha256: Digest | None = None
    mode: Literal["live", "request_capture"] | None = None
    operator_attestation: Literal["checked_eligible", "checked_ineligible", "unchecked", "not_applicable_local"] = "unchecked"
    auth_env_keys: list[EnvKeyName] = Field(default_factory=list)
    expected_api_key_source: Annotated[str, Field(max_length=128)] | None = None
    invocation_digest: Digest | None = None
    resolved_model: ModelName | None = None
    failed_checks: Annotated[list[CheckName], Field(max_length=32)] = Field(default_factory=list)

    @model_validator(mode="after")
    def _complete(self) -> "ProviderCertification":
        if self.certified:
            missing = [f for f in ("certified_at", "report_digest", "executable_sha256", "invocation_digest") if getattr(self, f) is None]
            if missing:
                raise ValueError(f"a certified route records {missing}")
            if self.mode != "live":
                raise ValueError("request-capture observations never certify a route")
            if self.operator_attestation not in ("checked_eligible", "not_applicable_local"):
                raise ValueError("certification requires the operator's checked background-use eligibility")
            if self.failed_checks:
                raise ValueError("a certified route has no failed checks")
        return self


class ProviderConfig(StrictModel):
    """Explicit backend/model/auth reference; never chosen because a CLI is on PATH.

    Local to one installation (``.recalith/provider.json``, never tracked):
    ``installation_id`` binds it, so a copied configuration is refused.
    Process backends (``claude_cli``, ``json_process``) launch ``executable``
    with ``invocation_args`` (which may contain ``{model}`` and
    ``{system_prompt}``); direct-API backends (``anthropic_messages``,
    ``openai_compatible``) have no executable and send one request to
    ``endpoint`` through the shipped stdlib transport (decision 0023).
    ``nonsecret_env`` holds nonsecret switches for the curator child;
    ``network_env_keys`` names managed proxy/TLS keys carried with the route.
    ``expected_resolved_model`` is the model an API provider must report back
    when it differs from ``configured_model`` (null: the same identifier).
    """

    provider_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
    installation_id: Id
    backend: Literal["claude_cli", "json_process", "anthropic_messages", "openai_compatible"]
    executable: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    configured_model: ModelName
    expected_resolved_model: ModelName | None = None
    auth_route: AuthRouteKind
    auth_env_keys: list[EnvKeyName]
    expected_api_key_source: Annotated[str, Field(max_length=128)] | None = None
    network_env_keys: list[EnvKeyName] = Field(default_factory=list)
    nonsecret_env: dict[EnvKeyName, Annotated[str, Field(max_length=1024)]] = Field(default_factory=dict)
    invocation_args: list[str] = Field(default_factory=list)
    endpoint: ApiEndpoint | None = None
    certification: ProviderCertification
    timeout_seconds: PositiveInt = 120
    max_wire_stdout_bytes: PositiveInt = WIRE_STDOUT_CAP
    max_stderr_bytes: PositiveInt = STDERR_CAP

    @property
    def is_api(self) -> bool:
        return self.backend in API_BACKENDS

    @model_validator(mode="after")
    def _no_unsafe_args(self) -> "ProviderConfig":
        if "--json-schema" in self.invocation_args:
            raise ValueError("--json-schema adds a model-visible tool on certified Claude builds (decision 0002)")
        for name in [*self.auth_env_keys, *self.network_env_keys, *self.nonsecret_env]:
            if _forbidden_env_name(name):
                raise ValueError("a route never names a host or recalith role marker")
        for name in self.nonsecret_env:
            if _CREDENTIAL_NAME.search(name):
                raise ValueError("nonsecret_env must not carry credentials")
        if self.max_wire_stdout_bytes > WIRE_STDOUT_CAP or self.max_stderr_bytes > STDERR_CAP:
            raise ValueError("provider output caps cannot exceed the hard 256 KiB wire / 64 KiB stderr limits")
        if self.backend in API_BACKENDS:
            self._check_api()
        else:
            if self.executable is None or self.endpoint is not None or self.expected_resolved_model is not None:
                raise ValueError("a process backend names its executable and has no API endpoint")
            if self.auth_route == "none" or not self.auth_env_keys:
                raise ValueError("an explicit auth route must name its environment keys")
        cert = self.certification
        if cert.certified:
            if self.backend in API_BACKENDS:
                if cert.resolved_model is None:
                    raise ValueError("a certified API route records the resolved model its provider reported")
                if cert.operator_attestation == "not_applicable_local" and not is_loopback_url(self.endpoint.url):  # type: ignore[union-attr]
                    raise ValueError("not_applicable_local attests only a loopback (local) endpoint; a remote provider's terms must be checked")
            else:
                if cert.host_version is None:
                    raise ValueError("a certified Claude CLI route records its host version")
                if cert.operator_attestation != "checked_eligible":
                    raise ValueError("certification requires the operator's checked background-use eligibility")
                if not cert.auth_env_keys:
                    raise ValueError("a certified route records its selected auth key names")
        return self

    def _check_api(self) -> None:
        endpoint = self.endpoint
        if self.executable is not None or self.invocation_args:
            raise ValueError("an API backend runs the shipped adapter: no executable and no argument array")
        if endpoint is None:
            raise ValueError("an API backend names its endpoint")
        if endpoint.dialect != BACKEND_DIALECT[self.backend]:
            raise ValueError(f"backend {self.backend} speaks the {BACKEND_DIALECT[self.backend]} dialect")
        if self.expected_api_key_source is not None:
            raise ValueError("expected_api_key_source is a Claude CLI diagnostic; an API route has none")
        if self.auth_route == "none":
            if self.auth_env_keys or endpoint.auth_header != "none" or not is_loopback_url(endpoint.url):
                raise ValueError("no auth is allowed only for a loopback endpoint, with no key names and no auth header")
        else:
            if self.auth_route != "env_api_key":
                raise ValueError("an API route reads its key from one named environment variable (env_api_key) or uses none")
            if len(self.auth_env_keys) != 1 or endpoint.auth_header == "none":
                raise ValueError("an API key route names exactly one environment key and the header that carries it")
