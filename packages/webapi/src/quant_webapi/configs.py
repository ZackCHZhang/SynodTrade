"""Read, validate and write the files under configs/ for the web editor.

Writes are guarded three ways: the text must parse, it must validate against the same
models a run uses (unless the caller forces it), and it must still be the version the
editor loaded (`etag`), so two browser tabs cannot silently overwrite each other. Every
overwritten or deleted file is first copied to `<configs>/.web_backups/`.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import jinja2
import jinja2.meta
import yaml
from pydantic import BaseModel, ValidationError

from quant_core.config import (
    STAGE_AGENT_ROLE,
    AgentConfig,
    AgentRef,
    ConfigError,
    LLMProvidersConfig,
    PipelineConfig,
    interpolate_env,
    resolve_model,
)
from quant_core.registry import AGENTS, CANDIDATE_SOURCES, SENTIMENT_SOURCES, STAGES
from quant_core.timeutil import utcnow
from quant_webapi.catalog import (
    CANDIDATE_SOURCE_OPTIONS,
    KIND_MODELS,
    KINDS,
    SENTIMENT_SOURCE_OPTIONS,
    STAGE_COMMON_KEYS,
    STAGE_OPTIONS,
    ConfigKind,
)

BACKUP_DIR = ".web_backups"
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
Loc = list[str | int]


class NotFoundError(LookupError):
    pass


class ConflictError(RuntimeError):
    pass


class InvalidConfigError(ValueError):
    def __init__(self, diagnostics: Diagnostics) -> None:
        super().__init__("; ".join(p.message for p in diagnostics.errors))
        self.diagnostics = diagnostics


@dataclass(slots=True)
class Problem:
    message: str
    loc: Loc = field(default_factory=list)
    line: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"message": self.message, "loc": self.loc, "line": self.line}


@dataclass(slots=True)
class Diagnostics:
    errors: list[Problem] = field(default_factory=list)
    warnings: list[Problem] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, message: str, loc: Loc | None = None, line: int | None = None) -> None:
        self.errors.append(Problem(message, loc or [], line))

    def warn(self, message: str, loc: Loc | None = None) -> None:
        self.warnings.append(Problem(message, loc or []))

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [p.as_dict() for p in self.errors],
            "warnings": [p.as_dict() for p in self.warnings],
            "info": self.info,
        }


def etag(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _validation_problems(exc: ValidationError, prefix: Loc) -> list[Problem]:
    return [
        Problem(
            f"{'.'.join(str(p) for p in [*prefix, *err['loc']]) or '(root)'}: {err['msg']}",
            [*prefix, *err["loc"]],
        )
        for err in exc.errors()
    ]


def _check(model: type[BaseModel], data: Any, diag: Diagnostics, prefix: Loc) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        diag.errors += _validation_problems(exc, prefix)
        return None


def _missing_env(data: Any, env: Mapping[str, str]) -> set[str]:
    """Names in ${NAME} references (without a default) that are not set."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, str):
            for match in _ENV_REF.finditer(node):
                if not env.get(match.group(1)) and match.group(2) is None:
                    found.add(match.group(1))
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for item in node.values():
                walk(item)

    walk(data)
    return found


class ConfigFiles:
    """The configs/ directory as seen by the web editor."""

    def __init__(self, root: Path, env: Mapping[str, str] | None = None) -> None:
        self.root = root
        self._env = env

    @property
    def env(self) -> Mapping[str, str]:
        return os.environ if self._env is None else self._env

    # ------------------------------------------------------------ paths

    def kind(self, name: str) -> ConfigKind:
        try:
            return KINDS[name]
        except KeyError:
            raise NotFoundError(f"unknown config kind {name!r}") from None

    def path(self, kind: ConfigKind, name: str) -> Path:
        if kind.file is not None:
            return self.root / kind.file
        if not re.fullmatch(kind.name_pattern, name):
            raise ValueError(f"invalid {kind.name} name {name!r}")
        assert kind.folder is not None
        return self.root / kind.folder / f"{name}{kind.ext}"

    def names(self, kind: ConfigKind) -> list[str]:
        if kind.file is not None:
            return [kind.name] if (self.root / kind.file).is_file() else []
        assert kind.folder is not None
        folder = self.root / kind.folder
        return sorted(p.name[: -len(kind.ext)] for p in folder.glob(f"*{kind.ext}"))

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    # ------------------------------------------------------------ read

    def list_all(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for kind in KINDS.values():
            entries = []
            for name in self.names(kind):
                path = self.path(kind, name)
                stat = path.stat()
                entries.append(
                    {
                        "name": name,
                        "path": self.rel(path),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
                        **self._summary(kind, path),
                    }
                )
            out[kind.name] = entries
        return out

    def _summary(self, kind: ConfigKind, path: Path) -> dict[str, Any]:
        """A few fields shown in lists (role of an agent, mode of a pipeline, ...)."""
        if not kind.yaml:
            return {}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return {"broken": True}
        if not isinstance(data, dict):
            return {"broken": True}
        if kind.name == "agents":
            return {
                "role": data.get("role"),
                "prompt_template": data.get("prompt_template"),
                "avatar": data.get("avatar"),
            }
        if kind.name == "pipelines":
            stages = data.get("stages") or []
            return {
                "mode": data.get("mode", "dry_run"),
                "account": data.get("account"),
                "stages": [s.get("type") for s in stages if isinstance(s, dict)],
                "universe_size": len(data.get("universe") or []),
            }
        return {}

    def read(self, kind_name: str, name: str) -> dict[str, Any]:
        kind = self.kind(kind_name)
        path = self.path(kind, name)
        if not path.is_file():
            raise NotFoundError(f"{kind.name} {name!r} not found")
        text = path.read_text(encoding="utf-8")
        return {
            "kind": kind.name,
            "name": name,
            "path": self.rel(path),
            "text": text,
            "etag": etag(text),
            "used_by": self.used_by(kind.name, name),
        }

    def load_data(self, kind_name: str, name: str) -> Any:
        """Parsed YAML of a file (no env interpolation); None if missing or broken."""
        kind = self.kind(kind_name)
        try:
            return yaml.safe_load(self.path(kind, name).read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError):
            return None

    # ------------------------------------------------------------ references

    def used_by(self, kind_name: str, name: str) -> list[str]:
        """Files that reference `name` (shown before deleting it)."""
        users: list[str] = []
        if kind_name in ("agents", "accounts", "risk"):
            for pipeline in self.names(KINDS["pipelines"]):
                data = self.load_data("pipelines", pipeline)
                if not isinstance(data, dict):
                    continue
                stages = [s for s in data.get("stages") or [] if isinstance(s, dict)]
                hit = (
                    (kind_name == "accounts" and data.get("account") == name)
                    or (
                        kind_name == "agents"
                        and any(
                            isinstance(ref, dict) and ref.get("agent") == name
                            for s in stages
                            for ref in s.get("agents") or []
                        )
                    )
                    or (
                        kind_name == "risk"
                        and any(
                            s.get("type") == "risk" and s.get("rules", "default") == name
                            for s in stages
                        )
                    )
                )
                if hit:
                    users.append(f"pipelines/{pipeline}")
        elif kind_name == "prompts":
            for agent in self.names(KINDS["agents"]):
                data = self.load_data("agents", agent)
                if isinstance(data, dict) and data.get("prompt_template") == f"prompts/{name}.j2":
                    users.append(f"agents/{agent}")
        if kind_name == "accounts":
            data = self.load_data("account_sync", "account_sync")
            if isinstance(data, dict) and name in (data.get("accounts") or []):
                users.append("account_sync")
        if kind_name == "pipelines":
            data = self.load_data("schedules", "schedules")
            if isinstance(data, dict):
                for i, job in enumerate(data.get("jobs") or []):
                    if isinstance(job, dict) and job.get("pipeline") == name:
                        users.append(f"schedules/jobs[{i}]")
        return users

    # ------------------------------------------------------------ validation

    def validate(self, kind_name: str, name: str, text: str) -> Diagnostics:
        kind = self.kind(kind_name)
        diag = Diagnostics()
        if not kind.yaml:
            self._validate_template(text, diag)
            return diag
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line = mark.line + 1 if mark is not None else None
            diag.error(f"YAML syntax error: {exc}", line=line)
            return diag
        if not isinstance(data, dict):
            diag.error("File content must be a mapping (key: value)")
            return diag
        missing = _missing_env(data, self.env)
        if missing:
            diag.warn(
                f"Environment variables not set: {', '.join(sorted(missing))} (the run will fail)"
            )
        env = {**{n: "1" for n in missing}, **self.env}
        try:
            data = interpolate_env(data, env)
        except ConfigError as exc:
            diag.error(str(exc))
            return diag
        if kind.key is not None and data.get(kind.key) != name:
            diag.error(f"{kind.key} must equal the file name {name!r}", [kind.key])
        if kind.name == "pipelines":
            self._validate_pipeline(data, diag)
        elif kind.name == "agents":
            self._validate_agent(data, diag)
        elif kind.name == "llm_providers":
            self._validate_providers(data, diag)
        elif kind.name == "schedules":
            self._validate_schedules(data, diag)
        elif kind.name == "account_sync":
            self._validate_account_sync(data, diag)
        else:
            _check(KIND_MODELS[kind.name], data, diag, [])
        return diag

    @staticmethod
    def _validate_template(text: str, diag: Diagnostics) -> None:
        env = jinja2.Environment(autoescape=False)
        try:
            ast = env.parse(text)
        except jinja2.TemplateSyntaxError as exc:
            diag.error(f"Template syntax error: {exc.message}", line=exc.lineno)
            return
        diag.info["variables"] = sorted(jinja2.meta.find_undeclared_variables(ast))

    def _validate_pipeline(self, data: dict[str, Any], diag: Diagnostics) -> None:
        pipeline = _check(PipelineConfig, data, diag, [])
        stages = data.get("stages")
        if not isinstance(stages, list):
            return
        known_stages = set(STAGES.names())
        accounts = set(self.names(KINDS["accounts"]))
        risk_rules = set(self.names(KINDS["risk"]))
        providers = self._provider_names()
        if pipeline is not None and pipeline.account not in accounts:
            diag.error(
                f"Account {pipeline.account!r} does not exist (configs/accounts/)", ["account"]
            )
        for i, stage in enumerate(stages):
            if not isinstance(stage, dict):
                continue
            loc: Loc = ["stages", i]
            stype = stage.get("type")
            if stype not in known_stages:
                diag.error(f"Unknown stage type {stype!r} (available: {sorted(known_stages)})", loc)
                continue
            options_model = STAGE_OPTIONS.get(str(stype))
            if options_model is not None:
                _check(options_model, stage, diag, loc)
                allowed = set(options_model.model_fields) | set(STAGE_COMMON_KEYS)
                for key in sorted(set(stage) - allowed):
                    diag.warn(
                        f"Stage {stype} has unknown option {key!r} (it will be ignored)",
                        [*loc, key],
                    )
            if stype == "selection":
                self._validate_candidate_sources(stage.get("sources") or [], diag, loc)
            if stype == "sentiment":
                self._validate_sentiment_sources(stage, diag, loc)
            if stype == "risk" and stage.get("rules", "default") not in risk_rules:
                diag.error(
                    f"Risk rules {stage.get('rules', 'default')!r} do not exist", [*loc, "rules"]
                )
            self._validate_agent_refs(str(stype), stage.get("agents") or [], providers, diag, loc)

    def _validate_candidate_sources(self, sources: Any, diag: Diagnostics, loc: Loc) -> None:
        if not isinstance(sources, list):
            return
        known = set(CANDIDATE_SOURCES.names())
        for j, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            sloc: Loc = [*loc, "sources", j]
            stype = source.get("type")
            if stype not in known:
                diag.error(f"Unknown candidate source {stype!r} (available: {sorted(known)})", sloc)
                continue
            model = CANDIDATE_SOURCE_OPTIONS.get(str(stype))
            if model is not None:
                options = {k: v for k, v in source.items() if k != "type"}
                _check(model, options, diag, sloc)

    def _validate_sentiment_sources(
        self, stage: dict[str, Any], diag: Diagnostics, loc: Loc
    ) -> None:
        known = set(SENTIMENT_SOURCES.names())
        for j, source in enumerate(stage.get("sources") or []):
            if source not in known:
                diag.error(
                    f"Unknown sentiment source {source!r} (available: {sorted(known)})",
                    [*loc, "sources", j],
                )
        options = stage.get("source_options") or {}
        if not isinstance(options, dict):
            return
        for source, values in options.items():
            model = SENTIMENT_SOURCE_OPTIONS.get(source)
            if model is not None and isinstance(values, dict):
                _check(model, values, diag, [*loc, "source_options", source])
            elif source not in known:
                diag.warn(
                    f"{source!r} in source_options is not a known source", [*loc, "source_options"]
                )

    def _validate_agent_refs(
        self,
        stage_type: str,
        refs: Any,
        providers: set[str] | None,
        diag: Diagnostics,
        loc: Loc,
    ) -> None:
        if not isinstance(refs, list):
            return
        role = STAGE_AGENT_ROLE.get(stage_type)
        if refs and role is None:
            diag.warn(f"Stage {stage_type} does not use agents", [*loc, "agents"])
        for j, ref in enumerate(refs):
            if not isinstance(ref, dict):
                continue
            rloc: Loc = [*loc, "agents", j]
            agent_id = ref.get("agent")
            data = self.load_data("agents", agent_id) if isinstance(agent_id, str) else None
            if not isinstance(data, dict):
                diag.error(f"Agent {agent_id!r} does not exist or cannot be read", [*rloc, "agent"])
                continue
            try:
                agent = AgentConfig.model_validate(data)
            except ValidationError:
                diag.error(f"Agent {agent_id!r} has an invalid config", [*rloc, "agent"])
                continue
            if role is not None and agent.role is not role:
                diag.error(
                    f"Stage {stage_type} needs an agent with role {role.value}, "
                    f"but {agent_id} is {agent.role.value}",
                    [*rloc, "agent"],
                )
            try:
                parsed = AgentRef.model_validate(ref)
                model = resolve_model(agent, parsed.model)
            except (ValidationError, ValueError) as exc:
                diag.error(f"Agent {agent_id}: invalid model config: {exc}", [*rloc, "model"])
                continue
            if providers is not None and model.provider not in providers:
                diag.error(
                    f"LLM provider {model.provider!r} is not defined in llm_providers.yaml",
                    [*rloc, "model", "provider"],
                )

    def _provider_names(self) -> set[str] | None:
        data = self.load_data("llm_providers", "llm_providers")
        if not isinstance(data, dict) or not isinstance(data.get("providers"), dict):
            return None
        return set(data["providers"])

    def _validate_agent(self, data: dict[str, Any], diag: Diagnostics) -> None:
        agent = _check(AgentConfig, data, diag, [])
        if agent is None:
            return
        template = self.root / "agents" / agent.prompt_template
        if not template.is_file():
            diag.error(
                f"Prompt template {agent.prompt_template} does not exist", ["prompt_template"]
            )
        if agent.registry_key not in AGENTS.names():
            diag.error(
                f"Implementation {agent.registry_key!r} is not registered "
                f"(available: {AGENTS.names()})",
                ["impl" if agent.impl else "role"],
            )

    def _validate_providers(self, data: dict[str, Any], diag: Diagnostics) -> None:
        config = _check(LLMProvidersConfig, data, diag, [])
        if config is None:
            return
        for name, provider in config.providers.items():
            if provider.api_key_env and not self.env.get(provider.api_key_env):
                diag.warn(
                    f"{name}: environment variable {provider.api_key_env} is not set "
                    "(agents using it will fail)",
                    ["providers", name, "api_key_env"],
                )

    def _validate_schedules(self, data: dict[str, Any], diag: Diagnostics) -> None:
        schedules = _check(KIND_MODELS["schedules"], data, diag, [])
        if schedules is None:
            return
        pipelines = set(self.names(KINDS["pipelines"]))
        for i, job in enumerate(data.get("jobs") or []):
            if isinstance(job, dict) and job.get("pipeline") not in pipelines:
                diag.error(
                    f"Pipeline {job.get('pipeline')!r} does not exist", ["jobs", i, "pipeline"]
                )

    def _validate_account_sync(self, data: dict[str, Any], diag: Diagnostics) -> None:
        config = _check(KIND_MODELS["account_sync"], data, diag, [])
        if config is None:
            return
        accounts = set(self.names(KINDS["accounts"]))
        for i, name in enumerate(config.accounts):
            if name not in accounts:
                diag.error(f"Account {name!r} does not exist (configs/accounts/)", ["accounts", i])

    # ------------------------------------------------------------ write

    def _backup(self, path: Path) -> None:
        if not path.is_file():
            return
        stamp = utcnow().strftime("%Y%m%dT%H%M%S%fZ")
        target = self.root / BACKUP_DIR / f"{self.rel(path)}.{stamp}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        """Write via a temp file; keep the file's line endings (CRLF on Windows checkouts)."""
        newline = "\r\n" if path.is_file() and b"\r\n" in path.read_bytes() else "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline=newline)
        os.replace(tmp, path)

    def write(
        self,
        kind_name: str,
        name: str,
        text: str,
        *,
        expected_etag: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Overwrite an existing file. `force` saves despite validation errors (never
        despite a YAML syntax error or a version conflict)."""
        kind = self.kind(kind_name)
        path = self.path(kind, name)
        if not path.is_file():
            raise NotFoundError(f"{kind.name} {name!r} not found")
        current = path.read_text(encoding="utf-8")
        if expected_etag is not None and etag(current) != expected_etag:
            raise ConflictError("The file was modified by someone else; reload it before saving")
        self._guard(kind, name, text, force)
        if text != current:
            self._backup(path)
            self._atomic_write(path, text)
        return self.read(kind.name, name)

    def create(
        self, kind_name: str, name: str, text: str, *, force: bool = False
    ) -> dict[str, Any]:
        kind = self.kind(kind_name)
        if kind.single:
            raise ValueError(f"{kind.name} is a single file and cannot be created")
        path = self.path(kind, name)
        if path.exists():
            raise ConflictError(f"{kind.name} {name!r} already exists")
        self._guard(kind, name, text, force)
        self._atomic_write(path, text)
        return self.read(kind.name, name)

    def delete(self, kind_name: str, name: str) -> None:
        kind = self.kind(kind_name)
        if kind.single:
            raise ValueError(f"{kind.name} is a single file and cannot be deleted")
        path = self.path(kind, name)
        if not path.is_file():
            raise NotFoundError(f"{kind.name} {name!r} not found")
        self._backup(path)
        path.unlink()

    def _guard(self, kind: ConfigKind, name: str, text: str, force: bool) -> None:
        diag = self.validate(kind.name, name, text)
        syntax = [
            p
            for p in diag.errors
            if p.message.startswith(("YAML syntax error", "Template syntax error"))
        ]
        if syntax or (diag.errors and not force):
            raise InvalidConfigError(diag)
