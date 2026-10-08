"""`avatar` is an optional display-only image URL on agent configs."""

from typing import Any

import pytest
from pydantic import ValidationError

from quant_core.config import AgentConfig

BASE: dict[str, Any] = {
    "agent_id": "value_investor",
    "role": "decision",
    "prompt_version": "v1",
    "persona": "p",
    "prompt_template": "prompts/test_v1.j2",
}


def test_avatar_is_optional() -> None:
    assert AgentConfig.model_validate(BASE).avatar is None


def test_avatar_accepts_http_urls() -> None:
    url = "https://upload.wikimedia.org/wikipedia/commons/thumb/x/xx/A.jpg/330px-A.jpg"
    assert AgentConfig.model_validate({**BASE, "avatar": url}).avatar == url


@pytest.mark.parametrize("bad", ["", "avatar.png", "javascript:alert(1)", "https://a b.jpg"])
def test_avatar_rejects_non_urls(bad: str) -> None:
    with pytest.raises(ValidationError):
        AgentConfig.model_validate({**BASE, "avatar": bad})
