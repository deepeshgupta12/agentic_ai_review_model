"""Step 02 use-case tests for contracts/v1 (UC-08 to UC-15).

Run:  .venv/bin/python -m unittest discover -s scripts/tests -v

Each class is one use case from logs/step-02/README.md. Besides confirming the
real contracts pass, most tests break something on purpose and check that the
break is caught.
"""
from __future__ import annotations

import copy
import itertools
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_openapi  # noqa: E402
import check_contracts as cc  # noqa: E402
import contract_tools as ct  # noqa: E402

C = ct.Contracts()
REGISTERED_PROJECTS = ("DLF Privana", "Conscient Parq", "Sobha Crescent", "M3M Forestia West", "M3M Antalya Hills")


def docs():
    routes, machines, journeys = cc._docs()
    return copy.deepcopy(routes), copy.deepcopy(machines), copy.deepcopy(journeys)


def fixture(file_name: str, name: str) -> dict:
    for item in ct.load_json(ct.FIXTURES / file_name)["cases"]:
        if item["name"] == name:
            return copy.deepcopy(item["instance"])
    raise KeyError(name)


def assert_problem(test: unittest.TestCase, problems: list[str], *fragments: str) -> None:
    matches = [p for p in problems if all(f in p for f in fragments)]
    test.assertTrue(matches, f"expected a problem containing {fragments}, got {problems}")


def roles() -> list[str]:
    return C.enum("common.schema.json#/$defs/Role")


class UC08VocabularyAndStateMachines(unittest.TestCase):
    """UC-08: one status vocabulary, and every status has a complete state machine."""

    def test_schema_files_are_valid_and_refs_resolve(self):
        self.assertEqual(ct.check_schema_files(C), [])

    def test_state_machines_and_vocabulary_pass(self):
        self.assertEqual(cc.check_vocabulary(C), [])

    def test_unreachable_state_detected(self):
        _, machines, _ = docs()
        ops = machines["machines"]["publication_operation"]
        ops["transitions"] = [t for t in ops["transitions"] if t["to"] != "rolled_back"]
        assert_problem(self, ct.check_state_machines(C, machines, roles()), "publication_operation", "'rolled_back' is unreachable")

    def test_terminal_state_with_exit_detected(self):
        _, machines, _ = docs()
        machines["machines"]["execution_job"]["transitions"].append({"from": "completed", "to": "queued", "actors": ["system"], "trigger": "x"})
        assert_problem(self, ct.check_state_machines(C, machines, roles()), "terminal state 'completed' has outgoing")

    def test_dead_end_state_detected(self):
        _, machines, _ = docs()
        job = machines["machines"]["execution_job"]
        job["transitions"] = [t for t in job["transitions"] if t["from"] != "retry_wait"]
        assert_problem(self, ct.check_state_machines(C, machines, roles()), "'retry_wait' has no way out")

    def test_model_is_never_an_actor(self):
        _, machines, _ = docs()
        machines["machines"]["content_lifecycle"]["transitions"][2]["actors"] = ["claude"]
        assert_problem(self, ct.check_state_machines(C, machines, roles()), "content_lifecycle", "invalid actors")

    def test_new_status_enum_without_machine_detected(self):
        contracts = ct.Contracts()
        contracts.schemas["common.schema.json"]["$defs"]["QueueStatus"] = {"enum": ["open", "closed"]}
        _, machines, _ = docs()
        assert_problem(self, ct.check_state_machines(contracts, machines, roles()), "QueueStatus", "no state machine")

    def test_inline_copy_of_a_status_enum_detected(self):
        contracts = ct.Contracts()
        job = contracts.schemas["operations.schema.json"]["$defs"]["Job"]
        job["properties"]["status"] = {"enum": C.enum("common.schema.json#/$defs/JobStatus")}
        assert_problem(self, ct.duplicate_status_enums(contracts), "operations.schema.json", "JobStatus")


class UC09ApiAndJourneys(unittest.TestCase):
    """UC-09: every mandatory journey has an allowed actor, a real API call and a valid state path."""

    def test_route_table_and_openapi_pass(self):
        self.assertEqual(cc.check_api(C), [])

    def test_journeys_pass(self):
        self.assertEqual(cc.check_journeys(C), [])

    def test_openapi_security_and_roles(self):
        spec = ct.load_json(build_openapi.OPENAPI)
        for path, methods in spec["paths"].items():
            for method, op in methods.items():
                with self.subTest(op=op["operationId"]):
                    if op["x-access"] == "session":
                        self.assertTrue(op["x-roles"])
                        if method != "get":
                            self.assertIn("csrfToken", op["security"][0])
                    elif op["x-access"] == "public":
                        self.assertEqual(op["security"], [])
                        self.assertTrue(path.startswith(("/v1/public/", "/v1/auth/login")))

    def test_separation_of_duties(self):
        routes, _, _ = docs()
        by_op = {r["operation_id"]: r for r in routes["routes"]}
        self.assertEqual(by_op["approveContentRevision"]["roles"], ["moderator"])
        for op in ("publish", "rollbackPublication", "unpublishProject"):
            self.assertEqual(by_op[op]["roles"], ["publisher"])

    def test_request_bodies_never_carry_actor_identity(self):
        routes, _, _ = docs()
        forbidden = {"actor", "user_id", "actor_id", "reviewer_id", "approved_by", "role"}
        for route in routes["routes"]:
            request = route.get("request")
            if not request or request.startswith("inline:"):
                continue
            names = _property_names(request)
            with self.subTest(op=route["operation_id"]):
                self.assertTrue(names)
                self.assertEqual(names & forbidden, set())

    def test_every_required_journey_is_covered(self):
        _, _, journeys = docs()
        covered = {tag for j in journeys["journeys"] for tag in j["covers"]}
        self.assertEqual(set(journeys["required_coverage"]) - covered, set())

    def test_role_not_allowed_detected(self):
        routes, machines, journeys = docs()
        journeys["journeys"][7]["steps"][1]["actor"] = "analyst"  # J08 publish
        assert_problem(self, ct.check_journeys(journeys, machines, routes), "J08 step 2", "may not call publish")

    def test_illegal_transition_detected(self):
        routes, machines, journeys = docs()
        journeys["journeys"][6]["steps"][2]["transitions"][0]["to"] = "approved"  # J07 draft -> approved
        assert_problem(self, ct.check_journeys(journeys, machines, routes), "J07", "no transition draft -> approved")

    def test_broken_state_chain_detected(self):
        routes, machines, journeys = docs()
        del journeys["journeys"][7]["steps"][2]["transitions"][1]  # J08 skips activating -> delivery_pending
        assert_problem(self, ct.check_journeys(journeys, machines, routes), "J08", "is in 'activating', not 'delivery_pending'")

    def test_missing_coverage_detected(self):
        routes, machines, journeys = docs()
        journeys["journeys"] = [j for j in journeys["journeys"] if "rollback" not in j["covers"]]
        assert_problem(self, ct.check_journeys(journeys, machines, routes), "no journey covers 'rollback'")

    def test_route_with_unknown_schema_detected(self):
        routes, _, _ = docs()
        routes["routes"][0]["request"] = "api.schema.json#/$defs/DoesNotExist"
        assert_problem(self, ct.check_routes(C, routes), "login", "does not resolve")


def _property_names(ref: str) -> set[str]:
    """Every property name reachable from a schema, following $refs once each (handles recursion)."""
    names: set[str] = set()
    seen: set[str] = set()

    def walk(node, current_file: str) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, current_file)
            return
        if not isinstance(node, dict):
            return
        if "$ref" in node:
            target_file, _, pointer = node["$ref"].partition("#")
            target = f"{target_file or current_file}#{pointer}"
            if target not in seen:
                seen.add(target)
                walk(C.resolve(target), target_file or current_file)
        for name, sub in node.get("properties", {}).items():
            names.add(name)
            walk(sub, current_file)
        for key in ("items", "anyOf", "allOf", "oneOf", "additionalProperties"):
            if key in node:
                walk(node[key], current_file)

    file_name = ref.partition("#")[0]
    seen.add(ref)
    walk(C.resolve(ref), file_name)
    return names


class UC10Fixtures(unittest.TestCase):
    """UC-10: fixtures cover the required cases; valid pass and invalid fail for the stated reason."""

    def test_fixtures_are_current_and_behave(self):
        self.assertEqual(cc.check_fixtures(C), [])

    def test_acceptance_cases_are_covered(self):
        tags = {tag for _, item in cc.fixture_cases() if item["expect"] == "valid" for tag in item["tags"]}
        for tag in ("multi_project_video", "unknown_date", "insufficient_evidence", "withdrawal"):
            self.assertIn(tag, tags)

    def test_real_input_file_matches_its_schema(self):
        data = ct.load_json(ROOT / "contracts" / "five-project-input-template.json")
        self.assertEqual(C.errors(data, "catalogue.schema.json#/$defs/ProjectInputFile"), [])

    def test_fixtures_never_describe_registered_projects(self):
        registered = ct.load_json(ROOT / "contracts" / "five-project-input-template.json")["projects"]
        rera = [r["id"] for p in registered for r in p.get("rera_ids", [])]
        for path in ct.FIXTURES.glob("*.json"):
            text = path.read_text(encoding="utf-8")
            for needle in (*REGISTERED_PROJECTS, *rera):
                with self.subTest(file=path.name, needle=needle):
                    self.assertNotIn(needle, text)

    def test_every_fixture_is_labelled_synthetic(self):
        for path in ct.FIXTURES.glob("*.json"):
            self.assertIn("Synthetic fixture", ct.load_json(path)["note"], path.name)


class UC11HashingAndAnchors(unittest.TestCase):
    """UC-11: one canonical hash across Python and JavaScript; offsets survive Hindi and emoji."""

    def test_hash_vectors_pass(self):
        self.assertEqual(cc.check_hashing(C), [])

    def test_key_order_is_utf16_not_code_point(self):
        value = {"ﬀ": 1, "😀": 2}
        self.assertEqual(ct.canonical_bytes(value).decode("utf-8"), '{"😀":2,"ﬀ":1}')
        self.assertEqual(sorted(value), ["ﬀ", "😀"])  # a naive code-point sort would disagree

    def test_one_character_edit_changes_the_hash(self):
        payload = fixture("content.json", "content_revision_approved")["payload"]
        edited = copy.deepcopy(payload)
        edited["considerations"][0]["text"] = edited["considerations"][0]["text"].replace(".", "!")
        self.assertNotEqual(ct.content_hash(payload), ct.content_hash(edited))

    def test_key_order_in_memory_does_not_change_the_hash(self):
        payload = fixture("content.json", "content_revision_approved")["payload"]
        reordered = dict(reversed(list(payload.items())))
        self.assertEqual(ct.content_hash(payload), ct.content_hash(reordered))

    def test_unsafe_values_are_rejected(self):
        for value in ({"a": 1.5}, {"a": 2**53}, {"a": "é"}, {"é": 1}, {"a": {1, 2}}):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ct.CanonicalError):
                    ct.canonical_bytes(value)

    def test_anchor_vectors_pass(self):
        self.assertEqual(cc.check_anchors(C), [])

    def test_offset_inside_a_surrogate_pair_rejected(self):
        with self.assertRaises(ValueError):
            ct.codepoint_offset("a😀b", 2)

    def test_javascript_agrees(self):
        self.assertEqual(cc.check_cross_language(C), [])


class UC12ApprovalAndPublicRead(unittest.TestCase):
    """UC-12: an edited payload cannot keep an approval; the public page never reads a draft."""

    def setUp(self):
        self.revision = fixture("content.json", "content_revision_approved")
        self.approval = fixture("content.json", "decision_final_approval")
        self.state = fixture("publication.json", "state_active")

    def test_rule_vectors_pass(self):
        self.assertEqual(cc.check_rules(C), [])

    def test_exact_approval_authorises(self):
        self.assertEqual(ct.approval_authorises(self.approval, self.revision, self.state), (True, []))

    def test_edit_as_new_revision_loses_approval(self):
        edited = copy.deepcopy(self.revision)
        edited["payload"]["heading"] += " (updated)"
        edited.update(id="rev_01JB0000000000000000000099", revision=2, payload_sha256=ct.content_hash(edited["payload"]))
        authorised, reasons = ct.approval_authorises(self.approval, edited, self.state)
        self.assertFalse(authorised)
        self.assertIn("approved payload hash differs from this payload", reasons)

    def test_silent_edit_under_same_revision_detected(self):
        tampered = copy.deepcopy(self.revision)
        tampered["payload"]["overview"]["text"] = "Everything is perfect."
        authorised, reasons = ct.approval_authorises(self.approval, tampered, self.state)
        self.assertFalse(authorised)
        self.assertIn("stored payload hash does not match the payload", reasons)

    def test_approval_by_non_person_rejected(self):
        self.approval["actor"] = {"kind": "system", "user_id": None, "role": None}
        self.assertIn("approval not made by a person", ct.approval_authorises(self.approval, self.revision, self.state)[1])

    def test_public_read_ignores_newer_draft(self):
        draft = fixture("content.json", "content_revision_edited")
        self.assertEqual(ct.public_revision(self.state, [draft, self.revision])["id"], self.revision["id"])

    def test_public_read_serves_nothing_when_disabled(self):
        self.state["serving_state"] = "temporarily_disabled"
        self.assertIsNone(ct.public_revision(self.state, [self.revision]))


class UC13AgentOutputs(unittest.TestCase):
    """UC-13: every model-backed agent has a small, closed output that Claude structured outputs accept."""

    def test_agent_outputs_pass(self):
        self.assertEqual(cc.check_agents(C), [])

    def test_bundle_is_self_contained(self):
        bundled = ct.bundle_schema(C, "agents.schema.json#/$defs/IdentityResult")
        refs = list(ct._refs(bundled))
        self.assertTrue(refs)
        self.assertTrue(all(r.startswith("#/$defs/") for r in refs), refs)

    def test_bundle_validates_like_the_original(self):
        bundled = ct.bundle_schema(C, "agents.schema.json#/$defs/IdentityResult")
        instance = fixture("agents.json", "identity_needs_review")
        self.assertEqual(list(Draft202012Validator(bundled).iter_errors(instance)), [])
        instance["segments"][0]["decision"] = "maybe"
        self.assertTrue(list(Draft202012Validator(bundled).iter_errors(instance)))

    def test_unsupported_features_detected(self):
        base = {"type": "object", "additionalProperties": False, "required": ["a"], "properties": {"a": {"type": "string"}}}
        cases = {
            "minLength": ({"a": {"type": "string", "minLength": 1}}, "keyword 'minLength'"),
            "optional property": ({"a": {"type": "string"}, "b": {"type": "string"}}, "every property must be required"),
            "format": ({"a": {"type": "string", "format": "regex"}}, "format 'regex'"),
            "oneOf": ({"a": {"oneOf": [{"type": "string"}, {"type": "null"}]}}, "keyword 'oneOf'"),
        }
        for name, (properties, expected) in cases.items():
            with self.subTest(case=name):
                schema = dict(base, properties=properties)
                assert_problem(self, ct.claude_subset_violations(schema), expected)
        assert_problem(self, ct.claude_subset_violations(dict(base, additionalProperties=True)), "additionalProperties: false")

    def test_recursive_schema_detected(self):
        with self.assertRaises(ValueError):
            ct.bundle_schema(C, "content.schema.json#/$defs/SafeJson")

    def test_models_cannot_report_failed(self):
        errors = C.errors({"outcome": "failed", "findings": [], "insufficiency_note": None}, "agents.schema.json#/$defs/SynthesisResult")
        assert_problem(self, errors, "'failed' is not one of")


class UC14TruthAndPublicationRules(unittest.TestCase):
    """UC-14: the schemas themselves keep counts from becoming truth, rights consistent and serving fail-closed."""

    def test_repetition_does_not_verify(self):
        claim = fixture("evidence.json", "claim_fact_verified")
        claim["independent_origin_count"] = 12
        claim["verification"]["primary_records"] = []
        assert_problem(self, C.errors(claim, "evidence.schema.json#/$defs/Claim"), "should be non-empty")

    def test_policy_rights_chain_exhaustive(self):
        base = fixture("sources.json", "policy_web_accepted")
        flags = ("collection_allowed", "ai_processing_allowed", "quotation_allowed", "derived_publication_allowed", "attribution_required")
        for values in itertools.product([False, True], repeat=5):
            policy = dict(base, **dict(zip(flags, values)))
            policy["retention_days"] = 90 if policy["collection_allowed"] else None
            chain_ok = (
                (not policy["ai_processing_allowed"] or policy["collection_allowed"])
                and (not policy["derived_publication_allowed"] or (policy["ai_processing_allowed"] and policy["attribution_required"]))
                and (not policy["quotation_allowed"] or policy["derived_publication_allowed"])
            )
            with self.subTest(values=values):
                self.assertEqual(C.errors(policy, "sources.schema.json#/$defs/SourcePolicy") == [], chain_ok)

    def test_only_people_decide(self):
        decision = fixture("content.json", "decision_final_approval")
        decision["actor"] = {"kind": "system", "user_id": None, "role": None}
        assert_problem(self, C.errors(decision, "content.schema.json#/$defs/ReviewDecision"), "'user' was expected")

    def test_serving_fails_closed_during_invalidation(self):
        state = fixture("publication.json", "state_disabled_after_withdrawal")
        state["serving_state"] = "active"
        self.assertTrue(C.errors(state, "publication.schema.json#/$defs/PublicationState"))

    def test_insufficient_evidence_has_no_content(self):
        run = fixture("operations.json", "run_insufficient_evidence")
        run["content_revision_id"] = "rev_01JB0000000000000000000001"
        self.assertTrue(C.errors(run, "operations.schema.json#/$defs/WorkflowRun"))


class UC15DocsAndSeedAlignment(unittest.TestCase):
    """UC-15: generated docs are current, screens use real operations, Step 01 data speaks the same vocabulary."""

    def test_docs_pass(self):
        self.assertEqual(cc.check_docs(C), [])

    def test_seed_alignment_passes(self):
        self.assertEqual(cc.check_seed(C), [])

    def test_whole_checker_passes(self):
        failed = [r for r in cc.run_all() if r["problems"]]
        self.assertEqual(failed, [])


class UC16StatusAndSourceReviews(unittest.TestCase):
    """UC-16: evidence and reviews agree with construction status; reviews are one real author's words (D27, D28)."""

    def setUp(self):
        self.rules = ct.content_rules()
        self.config = fixture("catalogue.json", "project_config")
        self.under_construction = [{"status": "under_construction", "applies_to": {"kind": "project", "rera_id": None}, "basis": "client_export", "as_of": "2026-09-25", "note": None}]

    def test_content_rules_pass(self):
        self.assertEqual(cc.check_content_rules(C), [])

    def test_every_registered_project_status_maps(self):
        for project in ct.load_json(ROOT / "contracts" / "five-project-input-template.json")["projects"]:
            with self.subTest(project=project["project_name"]):
                self.assertIsNotNone(ct.status_from_export_label(project["client_ref"]["status"], self.rules))

    def test_lived_here_before_possession_is_flagged(self):
        self.assertEqual(ct.consistency_flags("resident_experience", self.under_construction), ["occupancy_before_possession"])

    def test_buyer_perspective_is_not_flagged(self):
        self.assertEqual(ct.consistency_flags("owner_awaiting_possession", self.under_construction), [])

    def test_ready_phase_clears_the_flag_but_unnamed_phase_does_not(self):
        records = self.config["construction_status"]
        phase = records[1]["applies_to"]["rera_id"]
        self.assertEqual(ct.consistency_flags("resident_experience", records, phase), [])
        self.assertEqual(ct.consistency_flags("resident_experience", records, None), ["status_unknown"])

    def test_post_date_decides_the_status(self):
        history = [
            dict(self.under_construction[0], as_of="2025-01-01"),
            dict(self.under_construction[0], status="ready_to_move", as_of="2026-06-01"),
        ]
        self.assertEqual(ct.consistency_flags("resident_experience", history, on_date="2025-12-31"), ["occupancy_before_possession"])
        self.assertEqual(ct.consistency_flags("resident_experience", history, on_date="2026-06-02"), [])

    def test_resident_wording_blocked_before_possession(self):
        self.assertEqual(ct.wording_issues("Residents like the park.", "new_launch")["blocking"], ["residents"])
        self.assertEqual(ct.wording_issues("Buyers like the park.", "new_launch"), {"blocking": [], "advice": []})

    def test_review_must_keep_the_authors_words(self):
        review = fixture("evidence.json", "review_post_normalised")
        self.assertEqual(ct.rendering_problems(review["original_text"], review["text"], review["rendering"]), [])
        changed = review["text"].replace("six months", "a few weeks")
        assert_problem(self, ct.rendering_problems(review["original_text"], changed, review["rendering"]), "words differ")

    def test_review_text_has_no_dashes(self):
        review = fixture("evidence.json", "review_post_normalised")
        assert_problem(self, ct.rendering_problems(review["original_text"], review["original_text"], "verbatim"), "dash or hyphen")

    def test_review_comes_from_one_source(self):
        review = fixture("evidence.json", "review_post_normalised")
        review["source"] = [review["source"], {"id": "src_01JB0000000000000000000002", "revision": 1}]
        self.assertTrue(C.errors(review, "evidence.schema.json#/$defs/ReviewExcerpt"))

    def test_flagged_review_cannot_be_approved(self):
        review = fixture("evidence.json", "review_flagged_pending")
        review["review_status"] = "approved"
        assert_problem(self, C.errors(review, "evidence.schema.json#/$defs/ReviewExcerpt"), "expected to be empty")

    def test_model_cannot_paraphrase_a_review(self):
        output = fixture("agents.json", "review_candidates")
        output["reviews"][0]["rendering"] = "paraphrase"
        assert_problem(self, C.errors(output, "agents.schema.json#/$defs/ReviewCandidates"), "'paraphrase' is not one of")

    def test_page_reviews_are_credited_without_links(self):
        payload = fixture("content.json", "content_revision_approved")["payload"]
        self.assertTrue(payload["reviews"])
        self.assertEqual({r["polarity"] for r in payload["reviews"]} >= {"negative"}, True)
        for review in payload["reviews"]:
            with self.subTest(review=review["support"]["review"]["id"]):
                self.assertIsNone(review["source_url"])
                self.assertTrue(review["credit"]["platform"])

    def test_page_review_missing_from_manifest_detected(self):
        revision = fixture("content.json", "content_revision_approved")
        revision["manifest"]["reviews"] = revision["manifest"]["reviews"][1:]
        assert_problem(self, ct.manifest_problems(revision), "missing from the manifest")

    def test_page_review_with_dash_detected(self):
        revision = fixture("content.json", "content_revision_approved")
        revision["payload"]["reviews"][0]["text"] += " — really"
        assert_problem(self, ct.manifest_problems(revision), "dash or hyphen")


if __name__ == "__main__":
    unittest.main()
