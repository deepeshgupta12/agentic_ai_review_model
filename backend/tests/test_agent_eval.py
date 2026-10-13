"""UC-65: the agent evaluation runs the real agents and backend checks on the labelled synthetic set in a scratch
database and scores them; here with the scripted model, so the scores say nothing about a real model."""

from __future__ import annotations

from app.agents.evaluation import _rule_matches, evaluation_record, run_agent_eval
from app.agents.gateway import ModelGateway
from app.config import REPO_ROOT

from .test_workflow import ScriptedModel


def test_rules_match_on_aspect_polarity_type_and_words():
    claim = {
        "aspect": "possession",
        "polarity": "negative",
        "claim_type": "fact",
        "perspective": "x",
        "statement": "Moved to 2028.",
    }
    assert _rule_matches(claim, {"aspect": ["possession"], "polarity": ["negative", "neutral"]})
    assert not _rule_matches(claim, {"aspect": ["possession"], "polarity": ["positive"]})
    assert _rule_matches(claim, {"statement_contains": ["2028"], "claim_type": ["fact"]})
    assert _rule_matches(claim, {"any": True})


def test_the_evaluation_runs_every_agent_on_linked_fictional_posts_and_leaves_nothing_behind(
    mongo_client, contracts, settings
):
    model = ScriptedModel()
    gateway = ModelGateway(settings, contracts, client=model, sleep=lambda _s: None)
    before = set(mongo_client.list_database_names())
    result = run_agent_eval(
        mongo_client,
        contracts,
        settings,
        None,
        REPO_ROOT / "evals" / "agents" / "v1",
        REPO_ROOT / "evals" / "identity" / "v1" / "catalogue.json",
        gateway=gateway,
    )
    assert result["unlinked_documents"] == [], "every labelled post reaches the agents through identity"
    assert set(mongo_client.list_database_names()) == before, "the scratch database is dropped"
    assert {"A05", "A07", "A11"} <= set(model.calls)
    assert result["dataset"]["synthetic"] and result["documents"] == 15
    assert result["summary"]["forbidden_claims"] > 0, "the scripted model reads sarcasm literally and is caught"
    record = evaluation_record(result)
    assert (
        contracts.errors(
            {"id": "evl_01K00000000000000000000001", **record, "created_at": "2026-10-12T00:00:00Z"},
            "operations.schema.json#/$defs/EvaluationRun",
        )
        == []
    )
