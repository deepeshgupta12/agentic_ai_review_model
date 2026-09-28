"""Step 01 use-case tests for scripts/validate_inputs.py.

Run:  python3 -m unittest discover -s scripts/tests -v

Each class is one use case from logs/step-01/README.md. Tests mutate copies of
the real repository files, so they check both the rules and the current data.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_inputs as vi  # noqa: E402


def load(name: str):
    return json.loads(vi.DEFAULT_PATHS[name].read_text(encoding="utf-8"))


def policy_families() -> set[str]:
    return set(vi.validate_policies(load("policies"))[2])


def assert_error(test: unittest.TestCase, errors: list[str], *fragments: str) -> None:
    matches = [e for e in errors if all(fragment in e for fragment in fragments)]
    test.assertTrue(matches, f"expected an error containing {fragments}, got {errors}")


class UC01ProjectRegistration(unittest.TestCase):
    """UC-01: the five supplied projects register, and bad input is named precisely."""

    def setUp(self):
        self.data = load("projects")

    def test_supplied_file_has_five_valid_projects(self):
        errors, _, registrations = vi.validate_projects(self.data)
        self.assertEqual(errors, [])
        self.assertEqual(
            [r["project_name"] for r in registrations],
            ["DLF Privana", "Conscient Parq", "Sobha Crescent", "M3M Forestia West", "M3M Antalya Hills"],
        )

    def test_placeholder_is_reported_with_project_and_field(self):
        self.data["projects"][0]["locality"] = "<Locality>"
        errors, _, _ = vi.validate_projects(self.data)
        assert_error(self, errors, "projects[0] (DLF Privana)", "'locality'", "placeholder")

    def test_missing_required_field_is_reported(self):
        del self.data["projects"][2]["city"]
        errors, _, _ = vi.validate_projects(self.data)
        assert_error(self, errors, "projects[2] (Sobha Crescent)", "'city'", "missing")

    def test_fewer_than_five_projects_rejected(self):
        self.data["projects"].pop()
        errors, _, _ = vi.validate_projects(self.data)
        assert_error(self, errors, "exactly 5 projects", "found 4")

    def test_more_than_five_projects_rejected(self):
        extra = copy.deepcopy(self.data["projects"][0])
        extra.update(project_name="Extra Project", rera_ids=[], client_ref=None)
        self.data["projects"].append(extra)
        errors, _, _ = vi.validate_projects(self.data)
        assert_error(self, errors, "exactly 5 projects", "found 6")

    def test_optional_fields_may_be_absent(self):
        for project in self.data["projects"]:
            for field in ("alternate_names", "micromarket", "developer", "phase", "rera_ids", "reference_url", "client_ref"):
                project.pop(field, None)
        errors, _, registrations = vi.validate_projects(self.data)
        self.assertEqual(errors, [])
        self.assertEqual(len(registrations), 5)

    def test_unknown_field_rejected(self):
        self.data["projects"][1]["micromarkt"] = "New Gurgaon"
        errors, _, _ = vi.validate_projects(self.data)
        assert_error(self, errors, "unknown field 'micromarkt'")

    def test_duplicate_project_rejected(self):
        duplicate = copy.deepcopy(self.data["projects"][0])
        duplicate.update(rera_ids=[], client_ref=None)
        self.data["projects"][4] = duplicate
        errors, _, _ = vi.validate_projects(self.data)
        assert_error(self, errors, "slug 'dlf-privana-sector-76-gurgaon' duplicates")

    def test_rera_as_plain_string_rejected(self):
        self.data["projects"][1]["rera_ids"] = ["GGM/818/550/2024/45"]
        errors, _, _ = vi.validate_projects(self.data)
        assert_error(self, errors, "'id' and 'registered_name'", "D16")

    def test_same_rera_in_full_and_short_form_is_a_duplicate(self):
        self.data["projects"][1]["rera_ids"].append(
            {"id": "GGM/772/504/2023/116", "registered_name": "Copied registration"}
        )
        errors, _, _ = vi.validate_projects(self.data)
        assert_error(self, errors, "GGM/772/504/2023/116", "already used by projects[0]")

    def test_duplicate_client_id_rejected(self):
        self.data["projects"][3]["client_ref"]["project_id"] = "1170"
        errors, _, _ = vi.validate_projects(self.data)
        assert_error(self, errors, "the client project_id 1170", "already used")

    def test_user_spellings_are_kept_and_search_forms_are_separate(self):
        _, _, registrations = vi.validate_projects(self.data)
        antalya = registrations[4]
        self.assertEqual(antalya["project_name"], "M3M Antalya Hills")
        self.assertIn("m3m antalya hills phase ii", antalya["search_names"])
        self.assertEqual(self.data["projects"][4]["rera_ids"][1]["registered_name"], "M3M Antalya Hills Phase II")

    def test_export_status_labels_map_to_construction_status(self):
        _, _, registrations = vi.validate_projects(self.data)
        self.assertEqual(
            [r["construction_status"] for r in registrations],
            ["ready_to_move", "under_construction", "new_launch", "new_launch", "partially_ready"],
        )

    def test_unknown_status_label_rejected(self):
        self.data["projects"][2]["client_ref"]["status"] = "Coming Soon"
        errors, _, _ = vi.validate_projects(self.data)
        assert_error(self, errors, "projects[2] (Sobha Crescent)", "'Coming Soon' is not a known export status")

    def test_generic_single_word_name_is_flagged(self):
        _, warnings, _ = vi.validate_projects(self.data)
        self.assertTrue(any("'parq'" in w and "single word" in w for w in warnings), warnings)


class UC02SlugAndSearchConventions(unittest.TestCase):
    """UC-02: slugs, search forms and RERA IDs follow D19."""

    def test_slugs_for_the_five_projects(self):
        _, _, registrations = vi.validate_projects(load("projects"))
        self.assertEqual(
            [r["slug"] for r in registrations],
            [
                "dlf-privana-sector-76-gurgaon",
                "conscient-parq-sector-80-gurgaon",
                "sobha-crescent-sector-63a-gurgaon",
                "m3m-forestia-west-manesar-sector-9-gurgaon",
                "m3m-antalya-hills-sector-79-gurgaon",
            ],
        )

    def test_slug_folds_accents_and_punctuation(self):
        self.assertEqual(vi.slugify("Café Élan (Phase-II)", "Sector 63A", "Gurgaon"), "cafe-elan-phase-ii-sector-63a-gurgaon")

    def test_slug_is_deterministic(self):
        project = {"project_name": "Sobha Crescent", "locality": "Sector 63A", "city": "Gurgaon"}
        self.assertEqual(vi.project_slug(project), vi.project_slug(copy.deepcopy(project)))

    def test_long_slug_is_cut_at_a_word_boundary(self):
        slug = vi.slugify("word " * 40, "Sector 1", "Gurgaon")
        self.assertLessEqual(len(slug), vi.SLUG_MAX_LENGTH)
        self.assertFalse(slug.endswith("-"))
        self.assertTrue(all(part == "word" for part in slug.split("-")))

    def test_non_latin_only_name_gives_empty_slug_error(self):
        data = load("projects")
        data["projects"][0].update(project_name="डीएलएफ", locality="सेक्टर", city="गुड़गांव")
        errors, _, _ = vi.validate_projects(data)
        assert_error(self, errors, "slug is empty")

    def test_search_form_keeps_devanagari_marks(self):
        self.assertEqual(vi.normalise_text("  डीएलएफ   प्रिवाना "), "डीएलएफ प्रिवाना")

    def test_search_form_lowercases_and_strips_punctuation(self):
        self.assertEqual(vi.normalise_text("Commercial-01 In M3M Antalya Hills Phase-I"), "commercial 01 in m3m antalya hills phase i")

    def test_full_and_short_rera_forms_compare_equal(self):
        self.assertEqual(
            vi.normalise_rera_id("RC/REP/HARERA/GGM/772/504/2023/116"),
            vi.normalise_rera_id(" ggm/772/504/2023/116 "),
        )

    def test_unknown_rera_format_is_a_warning_not_an_error(self):
        data = load("projects")
        data["projects"][2]["rera_ids"][0]["id"] = "UPRERAPRJ12345"
        errors, warnings, _ = vi.validate_projects(data)
        self.assertEqual(errors, [])
        self.assertTrue(any("UPRERAPRJ12345" in w for w in warnings), warnings)


class UC03ConnectorMatrix(unittest.TestCase):
    """UC-03: every source is registered access_pending with a credential plan and go-live test."""

    def setUp(self):
        self.data = load("connectors")
        self.families = policy_families()

    def all_sources(self):
        return self.data["model_providers"] + self.data["connectors"]

    def test_matrix_validates(self):
        errors, _ = vi.validate_connectors(self.data, self.families)
        self.assertEqual(errors, [])

    def test_every_source_is_access_pending(self):
        self.assertEqual({s["id"]: s["status"] for s in self.all_sources() if s["status"] != "access_pending"}, {})

    def test_every_source_has_credential_plan_and_demonstration(self):
        for source in self.all_sources():
            with self.subTest(source=source["id"]):
                self.assertTrue(source["demonstration"].strip())
                self.assertTrue(source["credential_env"] or source.get("no_credential_reason"))

    def test_acquisition_order_follows_the_plan(self):
        order = {s["id"]: s["acquisition_order"] for s in self.all_sources()}
        self.assertLess(order["anthropic"], order["brave_search"])
        self.assertLess(order["brave_search"], order["firecrawl"])
        self.assertLess(order["firecrawl"], order["youtube_data_api"])
        for later in ("reddit_api", "x_api", "meta_graph_api", "listening_provider"):
            self.assertGreater(order[later], order["youtube_data_api"])

    def test_live_without_recorded_demonstration_rejected(self):
        self.data["connectors"][0]["status"] = "live"
        errors, _ = vi.validate_connectors(self.data, self.families)
        assert_error(self, errors, "brave_search", "'live' requires")

    def test_live_with_recorded_demonstration_accepted(self):
        self.data["connectors"][0].update(status="live", last_verified="2026-10-01", verification_ref="PROGRESS.md 2026-10-01")
        errors, _ = vi.validate_connectors(self.data, self.families)
        self.assertEqual(errors, [])

    def test_unknown_policy_family_rejected(self):
        self.data["connectors"][0]["policy_family"] = "somewhere_else"
        errors, _ = vi.validate_connectors(self.data, self.families)
        assert_error(self, errors, "policy_family 'somewhere_else' has no source policy")

    def test_missing_credential_reason_rejected(self):
        del self.data["connectors"][2]["no_credential_reason"]  # playwright_fetch
        errors, _ = vi.validate_connectors(self.data, self.families)
        assert_error(self, errors, "playwright_fetch", "no_credential_reason")

    def test_lowercase_env_name_rejected(self):
        self.data["connectors"][0]["credential_env"] = ["brave_key"]
        errors, _ = vi.validate_connectors(self.data, self.families)
        assert_error(self, errors, "brave_search", "UPPER_SNAKE_CASE")

    def test_one_of_group_needs_two_members(self):
        self.data["connectors"] = [c for c in self.data["connectors"] if c["id"] != "playwright_fetch"]
        errors, _ = vi.validate_connectors(self.data, self.families)
        assert_error(self, errors, "group 'web_extraction'", "at least two")


class UC04SourcePolicies(unittest.TestCase):
    """UC-04: source policies exist for every family and their rights are consistent."""

    def setUp(self):
        self.data = load("policies")

    def policy(self, family):
        return next(p for p in self.data["policies"] if p["family"] == family)

    def test_policies_validate(self):
        errors, _, _ = vi.validate_policies(self.data)
        self.assertEqual(errors, [])

    def test_every_connector_family_has_a_policy(self):
        families = {c["policy_family"] for c in load("connectors")["connectors"]}
        self.assertEqual(families - policy_families(), set())

    def test_families_without_an_agreement_are_blocked(self):
        for family in ("spoken_video_content", "reddit", "x", "meta", "quora", "linkedin", "listening_provider"):
            with self.subTest(family=family):
                policy = self.policy(family)
                self.assertFalse(policy["collection_allowed"])
                self.assertFalse(policy["ai_processing_allowed"])

    def test_generic_web_route_excludes_hosts_owned_by_other_families(self):
        self.policy("web_public_pages")["excluded_hosts"].remove("reddit.com")
        errors, _, _ = vi.validate_policies(self.data)
        assert_error(self, errors, "reddit.com", "excluded_hosts")

    def test_ai_processing_requires_collection(self):
        self.policy("reddit")["ai_processing_allowed"] = True
        errors, _, _ = vi.validate_policies(self.data)
        assert_error(self, errors, "reddit", "AI processing allowed without collection")

    def test_quotation_requires_derived_publication(self):
        policy = self.policy("youtube")
        policy.update(quotation_allowed=True, derived_publication_allowed=False)
        errors, _, _ = vi.validate_policies(self.data)
        assert_error(self, errors, "youtube", "quotation allowed without derived publication")

    def test_derived_publication_requires_attribution(self):
        self.policy("web_public_pages")["attribution_required"] = False
        errors, _, _ = vi.validate_policies(self.data)
        assert_error(self, errors, "web_public_pages", "requires attribution")

    def test_collection_requires_retention(self):
        self.policy("official_records")["retention_days"] = None
        errors, _, _ = vi.validate_policies(self.data)
        assert_error(self, errors, "official_records", "positive retention_days")

    def test_accepting_a_policy_without_owner_rejected(self):
        policy = self.policy("youtube")
        policy["status"] = "accepted"
        policy.pop("accepted_by", None)
        errors, _, _ = vi.validate_policies(self.data)
        assert_error(self, errors, "youtube", "accepted_on (date) and accepted_by")


class UC05OperatingDefaults(unittest.TestCase):
    """UC-05: defaults are provisional until accepted by a named person."""

    def setUp(self):
        self.data = load("defaults")

    def test_defaults_validate(self):
        errors, _ = vi.validate_defaults(self.data)
        self.assertEqual(errors, [])

    def test_nothing_is_accepted_without_owner_record(self):
        for key, item in self.data["items"].items():
            with self.subTest(item=key):
                if item["status"] == "accepted":
                    self.assertTrue(item.get("accepted_by") and item.get("accepted_on"))

    def test_accepting_without_owner_rejected(self):
        item = self.data["items"]["output_locale"]
        item["status"] = "accepted"
        item.pop("accepted_by", None)
        errors, _ = vi.validate_defaults(self.data)
        assert_error(self, errors, "output_locale", "accepted_on")

    def test_open_item_with_value_rejected(self):
        self.data["items"]["correction_owner"]["value"] = "Somebody"
        errors, _ = vi.validate_defaults(self.data)
        assert_error(self, errors, "correction_owner", "open item cannot have a value")

    def test_roles_match_the_api_contract(self):
        self.data["items"]["roles"]["value"] = ["admin", "editor"]
        errors, _ = vi.validate_defaults(self.data)
        assert_error(self, errors, "roles", "docs/03")

    def test_missing_required_item_rejected(self):
        del self.data["items"]["discovery_lookback_days"]
        errors, _ = vi.validate_defaults(self.data)
        assert_error(self, errors, "missing item 'discovery_lookback_days'")


class UC06RegisterAndSecrets(unittest.TestCase):
    """UC-06: DECISIONS.md stays in sync with the matrix and no secret enters the repo."""

    def setUp(self):
        self.decisions = vi.DEFAULT_PATHS["decisions"].read_text(encoding="utf-8")
        self.connectors = load("connectors")

    def test_registry_matches_the_matrix(self):
        self.assertEqual(vi.check_decisions_registry(self.decisions, self.connectors), [])

    def test_missing_registry_row_detected(self):
        text = "\n".join(line for line in self.decisions.splitlines() if "`x_api`" not in line)
        assert_error(self, vi.check_decisions_registry(text, self.connectors), "no row for `x_api`")

    def test_status_drift_detected(self):
        self.connectors["connectors"][0].update(status="live", last_verified="2026-10-01", verification_ref="log")
        assert_error(self, vi.check_decisions_registry(self.decisions, self.connectors), "`brave_search`", "'live'")

    def test_seed_files_contain_no_secrets(self):
        texts = {key: vi.DEFAULT_PATHS[key].read_text(encoding="utf-8") for key in ("projects", "connectors", "policies", "defaults")}
        self.assertEqual(vi.scan_for_secrets(texts), [])

    def test_secret_like_value_detected(self):
        fake = "sk-ant-" + "x" * 24
        assert_error(self, vi.scan_for_secrets({"seed/connectors.json": f'"key": "{fake}"'}), "secret-like")

    def test_env_file_is_gitignored(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".env", lines)


class UC07CommandLine(unittest.TestCase):
    """UC-07: the command the user runs gives the right exit code and output."""

    script = ROOT / "scripts" / "validate_inputs.py"

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(self.script), *args], capture_output=True, text=True, cwd=ROOT)

    def test_passes_on_repository_files(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Result: PASS", result.stdout)

    def test_fails_on_a_placeholder_file(self):
        data = load("projects")
        data["projects"][0]["project_name"] = "<Project 1 name>"
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(data), encoding="utf-8")
            result = self.run_cli("--projects", str(bad))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Result: FAIL", result.stdout)
        self.assertIn("'project_name' is still a placeholder", result.stdout)

    def test_fails_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "broken.json"
            bad.write_text("{ not json", encoding="utf-8")
            result = self.run_cli("--connectors", str(bad))
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid JSON", result.stdout)

    def test_json_output(self):
        result = self.run_cli("--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["result"], "pass")
        self.assertEqual(payload["summary"]["projects"], 5)
        self.assertEqual(payload["summary"]["connectors"]["by_status"], {"access_pending": 11})


if __name__ == "__main__":
    unittest.main()
