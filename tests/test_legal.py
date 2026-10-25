"""Legal information: drafts stay drafts, publication needs completeness + operator verification + exact-version
approval per document, and the money / enrolment interlock."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import legal_fixtures  # noqa: E402

from core import legal, rewards  # noqa: E402

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

APP = str(ROOT / "app.py")


def _current(name: str):
    """The module object the app is using now (it may reload modules during a full test run)."""
    import importlib
    return sys.modules.get(name) or importlib.import_module(name)


class RealDraftTests(unittest.TestCase):
    """The documents in legal/ are drafts: they can never be published, whatever the settings say."""

    def setUp(self):
        legal_fixtures.use_real()

    def test_pilot_activation_checklist_names_every_missing_requirement_once(self):
        issues = legal.pilot_activation_problems({})
        for shared in ("[legal] operator_verified", "[legal] contact_email", "[legal] registered_address"):
            self.assertEqual(sum(shared in i for i in issues), 1, shared)
        for title in ("Privacy Policy", "Terms of Use", "Friends & Family 10 terms"):
            self.assertIn(f"{title}: The document still carries the DRAFT notice.", issues)
            self.assertTrue(any(i.startswith(f"{title}: ") and "open item" in i for i in issues), title)
            self.assertTrue(any(i.startswith(f"{title}: The version is not final") for i in issues), title)
        for key in ("privacy", "terms", "pilot"):
            self.assertTrue(any(f"[legal.approved] {key} = " in i for i in issues), key)

    def test_pilot_activation_checklist_ignores_invented_settings_for_draft_documents(self):
        cfg = {"operator_verified": True, "contact_email": "privacy@example.com",
               "registered_address": "1 Example Street, Lagos", "approved": {k: legal.checksum(k) for k in legal.DOCUMENTS}}
        issues = legal.pilot_activation_problems(cfg)
        self.assertTrue(issues)                                   # the drafts themselves still block activation
        self.assertFalse(any("[legal] operator_verified" in i or "[legal.approved]" in i for i in issues))

    def test_drafts_cannot_be_published_even_with_every_setting(self):
        cfg = {"operator_verified": True, "contact_email": "privacy@example.com",
               "registered_address": "1 Example Street, Lagos", "approved": {k: legal.checksum(k) for k in legal.DOCUMENTS}}
        for key in legal.DOCUMENTS:
            issues = legal.problems(key, cfg)
            self.assertTrue(any("DRAFT" in i for i in issues), key)
            self.assertTrue(any("open item" in i for i in issues), key)
            self.assertTrue(any("not final" in i for i in issues), key)
        self.assertFalse(legal.live(cfg))
        self.assertFalse(legal.pilot_ready(cfg))
        self.assertEqual(legal.live_documents(cfg), [])

    def test_operator_identity(self):
        self.assertEqual(legal.operator_line(), "World Explorer — Operated by OKETORIAH KÖNIGREICH LTD.")
        for part in ("OKETORIAH KÖNIGREICH LTD", "RC 7160552", "30 September 2023", "Nigeria",
                     "private company limited by shares"):
            self.assertIn(part, legal.identification())
        self.assertIn("not yet verified", legal.identification(verified=False))

    def test_privacy_policy_matches_the_app(self):
        text = legal.document("privacy", {})
        for fact in ("Nigeria Data Protection", "we_consent", "we_aid", "we_handoff", "we_ref", "we_school",
                     "Supabase", "Streamlit", "Wikimedia", "Google", "at most 10 individually approved adults",
                     "Payments are not active", "Global Privacy Control", "NDPC"):
            self.assertIn(fact, text)
        self.assertIn(legal.TO_CONFIRM, text)                          # missing contact is marked, never invented

    def test_pilot_terms_limit_and_no_payments(self):
        text = legal.document("pilot", {})
        self.assertIn("at most **10** participants", text)
        self.assertIn("**18 or older**", text)
        self.assertIn("No money is currently payable", text)

    def test_founding_places_capped_at_fifty_and_the_pilot_at_ten(self):
        import dataclasses
        self.assertEqual(rewards.Settings().validate(), [])
        problems = dataclasses.replace(rewards.Settings(), max_places=51).validate()
        self.assertTrue(any("limited to 50" in p for p in problems))
        self.assertEqual(legal.PILOT_MAX_PLACES, 10)


class PublicationRuleTests(unittest.TestCase):
    """With completed documents: every requirement is needed, per document."""

    def setUp(self):
        legal_fixtures.use_completed()
        self.addCleanup(legal_fixtures.use_real)
        self.cfg = legal_fixtures.secrets()

    def test_complete_and_approved_documents_are_live(self):
        self.assertEqual(legal.live_documents(self.cfg), ["privacy", "terms", "pilot"])
        self.assertTrue(legal.live(self.cfg) and legal.pilot_ready(self.cfg))
        text = legal.document("privacy", self.cfg)
        self.assertIn("privacy@example.com", text)
        self.assertNotIn("{{", text)

    def test_every_requirement_is_needed(self):
        for change in ({"operator_verified": False}, {"operator_verified": "true"}, {"contact_email": ""},
                       {"contact_email": "not-an-email"}, {"registered_address": ""},
                       {"registered_address": "[address]"}, {"approved": {}},
                       {"approved": {"privacy": legal_fixtures.VERSION, "terms": legal_fixtures.checksum("terms")}},
                       {"approved": {"privacy": legal_fixtures.checksum("terms"), "terms": legal_fixtures.checksum("terms")}}):
            cfg = dict(self.cfg, **change)
            self.assertFalse(legal.doc_live("privacy", cfg), change)
            self.assertFalse(legal.live(cfg), change)

    def test_documents_are_approved_individually(self):
        cfg = legal_fixtures.secrets(docs=("privacy", "terms"))
        self.assertTrue(legal.live(cfg))                               # the general notice for every user ...
        self.assertFalse(legal.pilot_ready(cfg))                       # ... without opening the pilot
        self.assertEqual(legal.live_documents(cfg), ["privacy", "terms"])

    def test_company_is_never_shown_as_operator_before_verification(self):
        cfg = legal_fixtures.secrets(verified=False)
        self.assertEqual(legal.live_documents(cfg), [])
        self.assertTrue(all(any("operator" in i for i in legal.problems(k, cfg)) for k in legal.DOCUMENTS))

    def edited_copy(self, change):
        """A copy of the completed documents with the Privacy Policy edited by change(text)."""
        import tempfile, shutil
        tmp = tempfile.mkdtemp(prefix="we-legal-edit-")
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in legal_fixtures.FILES.values():
            shutil.copy(Path(legal_fixtures.completed_dir()) / name, Path(tmp) / name)
        path = Path(tmp) / "PRIVACY_POLICY.md"
        path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")
        return tmp

    def test_any_edit_unpublishes_until_approved_again_even_with_the_same_version(self):
        import os
        for change in (lambda t: t.replace("We do not sell personal data", "We may share personal data"),   # wording
                       lambda t: t + " ",                                                                       # one space
                       lambda t: t.replace(legal_fixtures.VERSION, "2026-12-01")):                              # version
            tmp = self.edited_copy(change)
            with mock.patch.dict(os.environ, {"WORLD_EXPLORER_LEGAL_DIR": tmp}):
                self.assertEqual(legal.version("privacy") in (legal_fixtures.VERSION, "2026-12-01"), True)
                self.assertFalse(legal.doc_live("privacy", self.cfg))
                self.assertTrue(any("Changed since it was approved" in i for i in legal.problems("privacy", self.cfg)))
                self.assertTrue(legal.doc_live("terms", self.cfg))                    # the others stay published
                self.assertTrue(legal.doc_live("pilot", self.cfg))
                renewed = dict(self.cfg, approved=dict(self.cfg["approved"], privacy=legal.checksum("privacy")))
                self.assertTrue(legal.doc_live("privacy", renewed))                  # approved again: published

    def test_line_endings_do_not_change_the_checksum(self):
        import os
        tmp = self.edited_copy(lambda t: t)
        crlf = Path(tmp) / "PRIVACY_POLICY.md"
        original = crlf.read_bytes().replace(b"\r\n", b"\n")
        crlf.write_bytes(original.replace(b"\n", b"\r\n"))
        with mock.patch.dict(os.environ, {"WORLD_EXPLORER_LEGAL_DIR": tmp}):
            self.assertTrue(legal.doc_live("privacy", self.cfg))

    def test_pilot_terms_id_binds_version_and_content(self):
        self.assertEqual(legal.pilot_terms_id(), legal_fixtures.pilot_terms_id())
        self.assertTrue(legal.pilot_terms_id().startswith(legal_fixtures.VERSION + "#"))


class InterlockTests(unittest.TestCase):
    """Public enrolment, withdrawals and payouts stay closed until the general documents are published; the pilot
    needs its own documents too."""

    def setUp(self):
        self.hooks = _current("ui.rewards_hooks")
        self.addCleanup(legal_fixtures.use_real)

    def check(self, legal_cfg, rewards_cfg, owner_on=True, pilot_on=True):
        with mock.patch.object(self.hooks.legal, "config", return_value=legal_cfg), \
                mock.patch.object(self.hooks, "config", return_value=rewards_cfg), \
                mock.patch.object(self.hooks, "owner_switch", return_value={"installed": True, "enabled": owner_on}), \
                mock.patch.object(self.hooks, "pilot_switch",
                                  return_value={"installed": True, "enabled": pilot_on, "invitation_only": True}):
            return (self.hooks.enabled(), self.hooks.payouts_active(), self.hooks.withdrawals_active(),
                    self.hooks.pilot_open())

    def test_everything_closed_with_drafts(self):
        legal_fixtures.use_real()
        all_on = {"enabled": True, "payouts_active": True, "withdrawals_active": True}
        self.assertEqual(self.check({"operator_verified": True}, all_on), (False, False, False, False))

    def test_published_documents_do_not_open_anything_by_themselves(self):
        cfg = legal_fixtures.secrets()
        self.assertEqual(self.check(cfg, {}, owner_on=False, pilot_on=False), (False, False, False, False))

    def test_pilot_needs_its_terms_public_rewards_do_not(self):
        cfg = legal_fixtures.secrets(docs=("privacy", "terms"))
        all_on = {"enabled": True, "payouts_active": True, "withdrawals_active": True}
        self.assertEqual(self.check(cfg, all_on), (True, True, True, False))

    def test_all_switches_on(self):
        cfg = legal_fixtures.secrets()
        all_on = {"enabled": True, "payouts_active": True, "withdrawals_active": True}
        self.assertEqual(self.check(cfg, all_on), (True, True, True, True))


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class SettingsSectionTests(unittest.TestCase):
    def render(self, cfg, owner):
        components = _current("ui.components")
        with mock.patch.object(components.legal, "config", return_value=cfg), \
                mock.patch.object(components.analytics, "is_owner", return_value=owner):
            return AppTest.from_function(_render_legal).run()

    def body(self, at):
        return " ".join(str(m.value) for m in at.markdown) + " ".join(str(c.value) for c in at.caption)

    def tearDown(self):
        legal_fixtures.use_real()

    def test_visitors_see_nothing_while_drafts(self):
        legal_fixtures.use_real()
        at = self.render({}, owner=False)
        self.assertFalse(at.expander)
        self.assertNotIn("OKETORIAH", self.body(at))

    def test_privacy_notice_published_for_everyone_without_the_pilot(self):
        at = self.render(legal_fixtures.secrets(docs=("privacy", "terms")), owner=False)
        self.assertEqual([x.label for x in at.expander], ["Legal information"])
        self.assertEqual([t.label for t in at.tabs], ["Privacy Policy", "Terms of Use"])
        self.assertIn("World Explorer — Operated by OKETORIAH KÖNIGREICH LTD.", self.body(at))
        self.assertFalse(at.warning)

    def test_owner_preview_is_labelled_and_never_claims_verification(self):
        legal_fixtures.use_real()
        at = self.render({}, owner=True)
        self.assertIn("draft preview", at.expander[0].label)
        warning = " ".join(w.value for w in at.warning)
        self.assertIn("not published", warning)
        self.assertIn("not yet verified", warning)
        self.assertTrue(all("(draft)" in t.label for t in at.tabs))

    def test_app_runs_with_and_without_legal_secrets(self):
        for cfg in (None, {}, legal_fixtures.secrets()):
            at = AppTest.from_file(APP, default_timeout=60)
            if cfg is not None:
                at.secrets["legal"] = cfg
            at.run()
            self.assertEqual([e.value for e in at.exception], [], cfg)


def _render_legal():
    from ui import components
    components.legal_information()



class PilotActivationCompleteTests(unittest.TestCase):
    def setUp(self):
        legal_fixtures.use_completed()
        self.addCleanup(legal_fixtures.use_real)

    def test_complete_legal_side_leaves_nothing_to_do(self):
        self.assertEqual(legal.pilot_activation_problems(legal_fixtures.secrets()), [])

    def test_missing_pilot_approval_alone_is_reported(self):
        issues = legal.pilot_activation_problems(legal_fixtures.secrets(docs=("privacy", "terms")))
        self.assertEqual(len(issues), 1)
        self.assertTrue(issues[0].startswith("Friends & Family 10 terms: Not approved"))

    def test_unverified_operator_is_reported(self):
        self.assertEqual(legal.pilot_activation_problems(legal_fixtures.secrets(verified=False)),
                         ["The company's role as operator and data controller is not confirmed ([legal] operator_verified)."])


if __name__ == "__main__":
    unittest.main()
