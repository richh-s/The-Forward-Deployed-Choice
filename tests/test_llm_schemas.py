"""Structured-output schemas must only use keywords the API accepts.

The Anthropic structured-output validator rejects `minimum`/`maximum` on
numeric properties with a 400. Because the tests mock the model, a bad schema
passes every unit test and then fails 100% of the time against the real API —
which is exactly how the judge shipped broken. These assert the schema shape
itself, so the failure is caught offline.
"""
import pytest

from engine.services.compose import COMPOSE_SCHEMA
from engine.services.judge import JUDGE_SCHEMA
from engine.services.reply_agent import REPLY_SCHEMA

# Keywords the structured-output validator does not support.
UNSUPPORTED = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
               "multipleOf"}

ALL_SCHEMAS = {
    "compose": COMPOSE_SCHEMA,
    "judge": JUDGE_SCHEMA,
    "reply": REPLY_SCHEMA,
}


def walk(node, path="$"):
    """Yield (path, dict) for every object in the schema tree."""
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


@pytest.mark.parametrize("name", sorted(ALL_SCHEMAS))
def test_schema_uses_no_unsupported_keywords(name):
    offenders = [
        (path, sorted(UNSUPPORTED & set(node)))
        for path, node in walk(ALL_SCHEMAS[name])
        if UNSUPPORTED & set(node)
    ]
    assert not offenders, (
        f"{name} schema uses keywords the API rejects with a 400: {offenders}"
    )


@pytest.mark.parametrize("name", sorted(ALL_SCHEMAS))
def test_schema_is_strict_and_well_formed(name):
    schema = ALL_SCHEMAS[name]
    assert schema["type"] == "object"
    assert schema.get("additionalProperties") is False, (
        f"{name}: additionalProperties must be False for strict output"
    )
    props, required = schema["properties"], schema["required"]
    assert set(required) <= set(props), (
        f"{name}: required names a property that does not exist"
    )
    assert set(props) == set(required), (
        f"{name}: every property should be required, else the model may omit it"
    )


def test_judge_scores_still_document_their_range():
    """The 0-1 bound moved from `minimum`/`maximum` into the description —
    if that text is lost, the model has nothing telling it the scale."""
    from engine.services.judge import WEIGHTS
    for dim in WEIGHTS:
        desc = JUDGE_SCHEMA["properties"][dim].get("description", "")
        assert "0.0" in desc and "1.0" in desc, f"{dim} lost its range hint"
