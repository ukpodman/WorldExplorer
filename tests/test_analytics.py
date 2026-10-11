"""Pilot measurement, owner dashboard access, analytics failure and guest → account progress.

Run:  python -m unittest discover tests
Pure metric tests need only Python; the app tests drive the real app with Streamlit's AppTest and replace the
network calls, so no Supabase project or Google account is contacted.
"""
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

APP = str(ROOT / "app.py")
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
STORAGE = {"url": "https://example.supabase.co", "server_key": "sb_secret_test"}


def ev(t, pid, event, mode=None, rid=None, signed=False, test=False, linked=None, device="phone"):
    return {"occurred_at": t.isoformat(), "anon_id": pid, "event": event, "mode": mode, "round_id": rid,
            "signed_in": signed, "test": test, "linked_id": linked, "device": device}


class MetricTests(unittest.TestCase):
    def setUp(self):
        from core import metrics
        self.m = metrics

    def test_first_round_completion_and_pending_rounds(self):
        d = NOW - timedelta(days=3)
        rows = [ev(d, "g:a", "round_start", "regular", "r1"), ev(d + timedelta(minutes=3), "g:a", "round_complete", "regular", "r1"),
                ev(d, "g:b", "round_start", "daily", "r2"),                                   # abandoned
                ev(NOW - timedelta(minutes=10), "g:c", "round_start", "regular", "r3"),         # may still finish
                ev(d, "g:d", "round_start", "regular", "r4"), ev(d + timedelta(hours=2), "g:d", "round_start", "regular", "r5"),
                ev(d + timedelta(hours=2, minutes=4), "g:d", "round_complete", "regular", "r5")]  # first round not finished
        out = self.m.compute(rows, NOW)
        self.assertEqual((out["first_round"]["n"], out["first_round"]["d"]), (1, 3))
        self.assertAlmostEqual(out["first_round"]["pct"], 100 / 3)

    def test_return_within_seven_days_counts_only_elapsed_windows(self):
        rows = [ev(NOW - timedelta(days=10), "g:a", "round_complete", "regular", "r1"),
                ev(NOW - timedelta(days=8), "g:a", "visit"),                                      # came back on day 2
                ev(NOW - timedelta(days=9, hours=23, minutes=50), "g:b", "round_complete", "daily", "r2"),
                ev(NOW - timedelta(days=9, hours=23, minutes=40), "g:b", "visit"),                # same UTC day: not a return
                ev(NOW - timedelta(days=2), "g:b", "visit"),                                      # after the 7-day window
                ev(NOW - timedelta(days=3), "g:c", "round_complete", "regular", "r3"),            # window not elapsed
                ev(NOW - timedelta(days=12), "g:d", "round_complete", "daily_replay", "r4")]     # replays don't start a cohort
        out = self.m.compute(rows, NOW)
        self.assertEqual((out["return7"]["n"], out["return7"]["d"], out["return7"]["pending"]), (1, 2, 1))

    def test_visitors_active_days_modes_and_signed_in(self):
        rows = [ev(NOW - timedelta(days=20), "g:a", "visit"), ev(NOW - timedelta(days=2), "g:a", "visit"),
                ev(NOW - timedelta(days=1), "g:a", "visit"),
                ev(NOW - timedelta(days=1), "g:b", "visit"),
                ev(NOW - timedelta(days=1), "u:c", "visit", signed=True),
                ev(NOW - timedelta(days=1), "u:c", "round_start", "daily", "d1", signed=True),
                ev(NOW - timedelta(days=1), "u:c", "round_complete", "daily", "d1", signed=True),
                ev(NOW - timedelta(days=1), "u:c", "round_start", "daily_replay", "d2", signed=True),
                ev(NOW - timedelta(days=1), "u:c", "round_start", "practice", "p1", signed=True),
                ev(NOW - timedelta(days=1), None, "consent_declined")]
        out = self.m.compute(rows, NOW, period_days=7)
        self.assertEqual((out["people"], out["new"], out["returning"]), (3, 2, 1))
        self.assertEqual((out["active3"]["n"], out["active3"]["d"]), (1, 3))
        self.assertEqual(out["rounds"]["daily"], {"starts": 1, "completions": 1, "people_started": 1, "people_completed": 1})
        self.assertEqual(out["rounds"]["daily_replay"]["starts"], 1)
        self.assertEqual(out["daily_person_days"], 1)
        self.assertEqual(out["rounds"]["practice"]["starts"], 1)
        self.assertEqual(out["rounds"]["regular"]["starts"], 0)
        self.assertEqual(out["signed_in"], {"signed_in": 1, "guest": 2, "linked": 0})
        self.assertEqual(out["declined"], 1)

    def test_guest_merged_into_account_and_test_traffic_excluded(self):
        d = NOW - timedelta(days=9)
        rows = [ev(d, "g:x", "round_start", "regular", "r1"), ev(d, "g:x", "round_complete", "regular", "r1"),
                ev(d + timedelta(minutes=5), "u:y", "link", linked="g:x", signed=True),
                ev(d + timedelta(days=1), "u:y", "visit", signed=True),
                ev(d, "g:owner", "visit", test=True), ev(d + timedelta(days=1), "g:owner", "round_start", "regular", "r9")]
        out = self.m.compute(rows, NOW)
        self.assertEqual(out["people"], 1)                              # g:x and u:y are one person; owner excluded
        self.assertEqual((out["return7"]["n"], out["return7"]["d"]), (1, 1))
        self.assertEqual(out["signed_in"]["linked"], 1)
        self.assertEqual(out["excluded_events"], 2)
        self.assertEqual(self.m.compute(rows, NOW, include_test=True)["people"], 2)

    def test_empty_data_has_no_rates(self):
        out = self.m.compute([], NOW)
        self.assertIsNone(out["first_round"]["pct"])
        self.assertEqual(out["people"], 0)


class FakeState(dict):
    __getattr__ = dict.__getitem__

    def __setattr__(self, key, value):
        self[key] = value


def fake_st(secrets=None, cookies=None, user=None, headers=None):
    class User(dict):
        is_logged_in = user is not None
    st = types.SimpleNamespace(session_state=FakeState(), secrets=secrets or {},
                               context=types.SimpleNamespace(cookies=cookies or {}, headers=headers or {}, url="https://x.streamlit.app/"),
                               user=User(user or {}))
    return st


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class TrackingTests(unittest.TestCase):
    """Event recording with a stand-in Streamlit (no network)."""

    def setUp(self):
        from core import accounts, analytics, cookies
        self.accounts, self.analytics, self.cookies = accounts, analytics, cookies

    def run_with(self, st, fn, post=None):
        sent = []
        post = post or (lambda url, key, table, row: sent.append((table, row)))
        with mock.patch.object(self.accounts, "st", st), mock.patch.object(self.analytics, "st", st), \
                mock.patch.object(self.cookies, "st", st), mock.patch.object(self.analytics, "SYNC", True), \
                mock.patch.object(self.analytics, "_post", post):
            fn()
        return sent

    def test_nothing_without_consent_or_when_switched_off(self):
        st = fake_st(secrets={"profiles": STORAGE, "analytics": {"enabled": True}})
        sent = self.run_with(st, lambda: (self.analytics.init_session(), self.analytics.log_visit(),
                                          self.analytics.track("round_start", "round_start:abc", mode="regular")))
        self.assertEqual(sent, [])                                    # no choice yet → nothing recorded
        st = fake_st(secrets={"profiles": STORAGE}, cookies={"we_consent": "granted", "we_aid": "a" * 32})
        sent = self.run_with(st, lambda: (self.analytics.init_session(), self.analytics.log_visit()))
        self.assertEqual(sent, [])                                    # owner has not switched analytics on

    def test_events_are_deduplicated_per_person_and_key(self):
        st = fake_st(secrets={"profiles": STORAGE, "analytics": {"enabled": True}},
                     cookies={"we_consent": "granted", "we_aid": "b" * 32},
                     headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile"})

        def flow():
            self.analytics.init_session()
            for _ in range(3):                                         # reruns
                self.analytics.log_visit()
                self.analytics.track_round("round_start", {"uid": "r1", "mode": "daily", "day": "2026-10-11"})
            self.analytics.track_round("round_complete", {"uid": "r1", "mode": "daily", "day": "2026-10-11"})
        sent = self.run_with(st, flow)
        rows = [r for _, r in sent]
        self.assertEqual([r["event"] for r in rows], ["visit", "round_start", "round_complete"])
        self.assertEqual({r["anon_id"] for r in rows}, {"g:" + "b" * 32})
        self.assertEqual(rows[1]["device"], "phone")
        self.assertEqual(len({r["event_key"] for r in rows}), 3)
        for r in rows:                                                 # nothing personal in a row
            self.assertFalse({"email", "name", "ip", "answer", "user_agent"} & set(r))

    def test_one_first_daily_completion_per_person_and_day(self):
        st = fake_st(secrets={"profiles": STORAGE, "analytics": {"enabled": True}},
                     cookies={"we_consent": "granted", "we_aid": "f" * 32})

        def flow():
            self.analytics.init_session()
            for uid in ("r1", "r2"):        # e.g. a guest who reloaded and played today's challenge again as "first"
                self.analytics.track_round("round_complete", {"uid": uid, "mode": "daily", "day": "2026-10-11"})
            self.analytics.track_round("round_complete", {"uid": "r3", "mode": "daily", "day": "2026-10-12"})
            self.analytics.track_round("round_complete", {"uid": "r4", "mode": "daily_replay", "day": "2026-10-12"})
        rows = [r for _, r in self.run_with(st, flow)]
        self.assertEqual([(r["mode"], r["day"]) for r in rows],
                         [("daily", "2026-10-11"), ("daily", "2026-10-12"), ("daily_replay", "2026-10-12")])

    def test_cookie_writes_are_rendered_once(self):
        st = fake_st()
        with mock.patch.object(self.cookies, "st", st):
            self.cookies.write("we_consent", "granted", 100)
            self.assertIn("we_consent", self.cookies.script())
            self.assertEqual(self.cookies.script(), "")             # an old tab cannot re-assert a stale choice
            self.cookies.write("we_aid", "<script>", 100)           # invalid values are never written
            self.assertEqual(self.cookies.script(), "")

    def test_global_privacy_control_counts_as_no_thanks(self):
        st = fake_st(secrets={"profiles": STORAGE, "analytics": {"enabled": True}}, headers={"Sec-GPC": "1"})
        self.run_with(st, self.analytics.init_session)
        self.assertEqual(st.session_state.an_consent, "denied")

    def test_consent_choice_writes_only_the_needed_cookies(self):
        st = fake_st(secrets={"profiles": STORAGE, "analytics": {"enabled": True}})
        sent = self.run_with(st, lambda: (self.analytics.init_session(), self.analytics.deny()))
        self.assertEqual(st.session_state.cookie_writes["we_consent"][0], "denied")
        self.assertEqual(st.session_state.cookie_writes["we_aid"], ("", 0))   # no id kept
        self.assertEqual([(t, r["event"], r["anon_id"]) for t, r in sent],
                         [("world_explorer_events", "consent_declined", None)])
        st = fake_st(secrets={"profiles": STORAGE, "analytics": {"enabled": True}})
        self.run_with(st, lambda: (self.analytics.init_session(), self.analytics.grant()))
        self.assertRegex(st.session_state.cookie_writes["we_aid"][0], r"^[0-9a-f]{32}$")

    def test_signed_in_players_get_a_salted_one_way_id(self):
        user = {"iss": "https://accounts.google.com", "sub": "google-subject-4711", "email": "ada@example.com", "email_verified": True}
        st = fake_st(secrets={"profiles": STORAGE, "analytics": {"enabled": True, "salt": "s1"}},
                     cookies={"we_consent": "granted", "we_aid": "c" * 32}, user=user)
        sent = self.run_with(st, lambda: (self.analytics.init_session(), self.analytics.log_visit()))
        rows = [r for _, r in sent]
        self.assertEqual([r["event"] for r in rows], ["visit", "link"])   # this browser's guest id joins the account
        self.assertTrue(rows[0]["anon_id"].startswith("u:") and rows[0]["signed_in"])
        self.assertNotIn("4711", rows[0]["anon_id"])
        self.assertNotIn("ada", rows[0]["anon_id"])
        self.assertEqual(rows[1]["linked_id"], "g:" + "c" * 32)

    def test_network_failure_is_silent(self):
        st = fake_st(secrets={"profiles": STORAGE, "analytics": {"enabled": True}},
                     cookies={"we_consent": "granted", "we_aid": "d" * 32})

        def broken(*args):
            raise OSError("supabase down")
        self.run_with(st, lambda: (self.analytics.init_session(), self.analytics.log_visit(),
                                   self.analytics.track_round("round_start", {"uid": "x", "mode": "regular"})), post=broken)

    def test_double_click_on_start_creates_one_round(self):
        from ui import state as ui_state
        from core import badges, daily, records
        st = fake_st(secrets={"profiles": STORAGE, "analytics": {"enabled": True}},
                     cookies={"we_consent": "granted", "we_aid": "e" * 32})
        st.session_state.update({k: (list(v) if isinstance(v, list) else v) for k, v in ui_state.DEFAULTS.items()})
        st.session_state.update(stats=badges.empty_stats(), records=records.empty_records(), daily=daily.empty_daily(), mistakes=[])
        settings = {"continent": "World", "country_id": "all", "category": "Mixed", "difficulty": "Medium", "count": 5,
                    "timer": False, "flags": True, "collection": "UN member and observer states"}
        clock = [1000.0]

        def flow():
            with mock.patch.object(ui_state, "st", st), mock.patch.object(ui_state.time, "monotonic", lambda: clock[0]):
                self.analytics.init_session()
                ui_state.start_round(settings)
                first = st.session_state.quiz["uid"]
                clock[0] += 0.4
                ui_state.start_round(settings)                       # second click 0.4 s later: same round
                self.assertEqual(st.session_state.quiz["uid"], first)
                clock[0] += 5
                ui_state.start_round(settings)                       # a deliberate new start later: new round
                self.assertNotEqual(st.session_state.quiz["uid"], first)
        sent = self.run_with(st, flow)
        self.assertEqual([r["event"] for _, r in sent], ["round_start", "round_start"])

    def test_owner_check_needs_verified_listed_email(self):
        cases = [(None, False), ({"email": "owner@example.com", "email_verified": True}, True),
                 ({"email": "OWNER@example.com", "email_verified": True}, True),
                 ({"email": "owner@example.com", "email_verified": False}, False),
                 ({"email": "someone@example.com", "email_verified": True}, False)]
        for claims, expected in cases:
            user = dict(claims, iss="https://accounts.google.com", sub="1") if claims else None
            st = fake_st(secrets={"analytics": {"owner_emails": ["owner@example.com"]}}, user=user)
            with mock.patch.object(self.accounts, "st", st), mock.patch.object(self.analytics, "st", st):
                self.assertEqual(self.analytics.is_owner(), expected, claims)
        st = fake_st(secrets={"analytics": {"owner_emails": ["owner@example.com"]}},
                     user={"iss": "https://other-idp.example", "sub": "1", "email": "owner@example.com", "email_verified": True})
        with mock.patch.object(self.accounts, "st", st), mock.patch.object(self.analytics, "st", st):
            self.assertFalse(self.analytics.is_owner())                 # another identity provider is not enough
        st = fake_st(secrets={}, user={"iss": "https://accounts.google.com", "sub": "1", "email": "owner@example.com", "email_verified": True})
        with mock.patch.object(self.accounts, "st", st), mock.patch.object(self.analytics, "st", st):
            self.assertFalse(self.analytics.is_owner())                 # no owner list → nobody


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class ConsentSyncTests(unittest.TestCase):
    """Withdrawal reaches every open tab, queued events are dropped, Global Privacy Control always wins."""

    AID = "9" * 32

    def setUp(self):
        from core import accounts, analytics, cookies
        self.accounts, self.analytics, self.cookies = accounts, analytics, cookies
        analytics._CHOICES.clear()
        self.sent = []

    def tab(self, consent="granted", headers=None, user=None):
        cookies = {"we_consent": consent, "we_aid": self.AID} if consent else {}
        st = fake_st(secrets={"profiles": STORAGE, "analytics": {"enabled": True}}, cookies=cookies,
                     headers=headers, user=user)
        self.do(st, self.analytics.init_session)
        return st

    def do(self, st, fn, sync=True):
        with mock.patch.object(self.accounts, "st", st), mock.patch.object(self.analytics, "st", st), \
                mock.patch.object(self.cookies, "st", st), mock.patch.object(self.analytics, "SYNC", sync), \
                mock.patch.object(self.analytics, "_post", lambda url, key, table, row: self.sent.append(row)):
            return fn()

    def start(self, st, uid):
        self.do(st, lambda: self.analytics.track_round("round_start", {"uid": uid, "mode": "regular"}))

    def test_withdrawal_in_one_tab_stops_the_others_without_reload(self):
        a, b = self.tab(), self.tab()
        self.start(a, "1111111111111111")
        self.do(b, self.analytics.deny)                                # "No thanks" in tab B
        self.start(a, "2222222222222222")                              # tab A keeps playing, no reload
        self.do(a, self.analytics.init_session)                        # A's next page update
        self.assertEqual([r["round_id"] for r in self.sent if r["event"] == "round_start"], ["1111111111111111"])
        self.assertEqual(a.session_state.an_consent, "denied")          # A's Settings switch now shows "off"
        self.assertIsNone(a.session_state.an_guest_id)

    def test_queued_events_are_not_sent_after_withdrawal(self):
        a, b = self.tab(), self.tab()
        import queue
        q = queue.Queue()
        alive = types.SimpleNamespace(is_alive=lambda: True)
        with mock.patch.object(self.analytics, "_queue", q), mock.patch.object(self.analytics, "_worker", alive):
            self.do(a, lambda: (self.analytics.log_visit(),
                                self.analytics.track_round("round_start", {"uid": "3333333333333333", "mode": "daily"})),
                    sync=False)
            self.assertEqual(q.qsize(), 2)                              # waiting in the background queue
            self.do(b, self.analytics.deny)
            delivered = [self.analytics._deliver(*q.get()[1]) for _ in range(q.qsize())]
        self.assertEqual(delivered, [False, False])
        self.assertEqual([r["event"] for r in self.sent], [])

    def test_allow_again_in_the_same_browser_resumes_other_tabs(self):
        a, b = self.tab(), self.tab()
        self.do(b, self.analytics.deny)
        self.do(b, self.analytics.grant)
        self.do(a, self.analytics.init_session)
        self.assertEqual((a.session_state.an_consent, a.session_state.an_guest_id), ("granted", self.AID))

    def test_allow_on_one_device_never_switches_on_another(self):
        user = {"iss": "https://accounts.google.com", "sub": "acct", "email": "ada@example.com"}
        desktop = self.tab(consent="denied", user=user)                 # said "No thanks" on the computer
        phone = fake_st(secrets={"profiles": STORAGE, "analytics": {"enabled": True}},
                        cookies={"we_consent": "granted", "we_aid": "8" * 32}, user=user)
        self.do(phone, self.analytics.init_session)
        self.do(phone, self.analytics.grant)                            # "Allow" on the phone, same account
        self.do(desktop, self.analytics.init_session)
        self.assertEqual(desktop.session_state.an_consent, "denied")
        self.do(desktop, self.analytics.deny)                           # "No thanks" reaches every session
        self.do(phone, self.analytics.init_session)
        self.assertEqual(phone.session_state.an_consent, "denied")

    def test_global_privacy_control_overrides_an_earlier_allow(self):
        open_tab = self.tab()                                           # opened before GPC was switched on
        gpc_tab = self.tab(headers={"Sec-GPC": "1"})                    # cookie still says "granted"
        ss = gpc_tab.session_state
        self.assertEqual((ss.an_consent, ss.an_guest_id), ("denied", None))
        self.assertEqual(ss.cookie_writes["we_aid"], ("", 0))           # the id is removed from the browser
        self.assertFalse(self.do(gpc_tab, self.analytics.needs_choice)) # not asked
        self.do(gpc_tab, self.analytics.grant)                          # cannot be overridden by "Allow"
        self.assertEqual(ss.an_consent, "denied")
        self.start(gpc_tab, "4444444444444444")
        self.start(open_tab, "5555555555555555")                        # the older tab stops as well
        self.assertEqual(self.sent, [])
        st = fake_st(secrets={"profiles": STORAGE, "analytics": {"enabled": True}},     # reported by the page script
                     cookies={"we_consent": "granted", "we_aid": self.AID, "we_gpc": "1"})
        self.do(st, self.analytics.init_session)
        self.assertEqual(st.session_state.an_consent, "denied")


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class AppAnalyticsTests(unittest.TestCase):
    """The real app with analytics switched on and the network replaced."""

    def new(self, post, page=None, secrets_extra=None):
        at = AppTest.from_file(APP, default_timeout=60)
        at.secrets["profiles"] = STORAGE
        at.secrets["analytics"] = dict({"enabled": True, "owner_emails": ["owner@example.com"]}, **(secrets_extra or {}))
        if page:
            at.session_state["page"] = page
        self.patches = [mock.patch("core.analytics.SYNC", True), mock.patch("core.analytics._post", post)]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        return at.run()

    def finish(self, at, pattern):
        for i, ok in enumerate(pattern):
            q = at.session_state["quiz"]
            qn = q["questions"][i]
            pick = qn["answer"] if ok else next(c for c in qn["choices"] if c != qn["answer"])
            at.button(key=f"answer_{q['serial']}_{i}_{qn['choices'].index(pick)}").click().run()
            at.button(key=f"next_{q['serial']}_{i}").click().run()

    def test_rounds_are_counted_once_by_mode(self):
        rows = []
        at = self.new(lambda url, key, table, row: rows.append(row))
        self.assertEqual(rows, [])                                     # asks first, records nothing
        self.assertTrue(at.button(key="consent_allow"))
        at.button(key="consent_allow").click().run()
        at.button(key="explore_daily").click().run()
        at.button(key="explore_daily").click().run() if at.session_state["page"] == "Explore" else None
        self.finish(at, [True, False, True, True, False])
        at.run(); at.run()                                             # reruns / reconnect-like refreshes
        at.button(key="play_again").click().run()                     # practice replay
        self.finish(at, [False] * 5)
        at.button(key="results_practise").click().run()
        n = len(at.session_state["quiz"]["questions"])
        self.finish(at, [True] * n)
        at.button(key="nav_Quiz").click().run()
        at.button(key="quiz_settings").click().run() if [b for b in at.button if b.key == "quiz_settings"] else None
        at.button(key="start_quiz").click().run()
        at.button(key="start_quiz").click().run() if [b for b in at.button if b.key == "start_quiz"] else None
        events = [(r["event"], r["mode"]) for r in rows]
        self.assertEqual(events.count(("visit", None)), 1)
        self.assertEqual(events.count(("round_start", "daily")), 1)
        self.assertEqual(events.count(("round_complete", "daily")), 1)
        self.assertEqual(events.count(("round_start", "daily_replay")), 1)
        self.assertEqual(events.count(("round_complete", "daily_replay")), 1)
        self.assertEqual(events.count(("round_start", "practice")), 1)
        self.assertEqual(events.count(("round_complete", "practice")), 1)
        self.assertEqual(events.count(("round_start", "regular")), 1)  # a double click starts one round
        self.assertEqual(len({r["event_key"] for r in rows}), len(rows))
        self.assertEqual([e.value for e in at.exception], [])

    def test_analytics_failure_never_blocks_play(self):
        def broken(*args):
            raise OSError("down")
        at = self.new(broken)
        at.button(key="consent_allow").click().run()
        at.button(key="explore_daily").click().run()
        self.finish(at, [True] * 5)
        self.assertEqual(at.session_state["rounds_finished"], 1)
        self.assertGreater(at.session_state["points"], 0)
        self.assertEqual(at.session_state["daily"]["streak"], 1)
        self.assertEqual([e.value for e in at.exception], [])

    def test_privacy_switch_is_locked_off_with_global_privacy_control(self):
        with mock.patch("core.analytics._header", lambda name: "1" if name == "Sec-GPC" else ""):
            at = self.new(lambda *a: None)
            self.assertEqual([b for b in at.button if b.key == "consent_allow"], [])   # not asked
            at.button(key="settings_menu").click().run()
            toggle = at.toggle(key="privacy_statistics")
            self.assertTrue(toggle.disabled)
            self.assertFalse(toggle.value)
            self.assertTrue(any("Global Privacy Control" in c.value for c in at.caption))
        self.assertEqual([e.value for e in at.exception], [])

    def test_owner_dashboard_is_server_side_protected(self):
        fetched = []

        def fake_fetch(table, columns, order):
            fetched.append(table)
            return []
        with mock.patch("core.analytics.fetch", fake_fetch):
            at = self.new(lambda *a: None, page="Owner")                # guest
            self.assertTrue(any("not available" in m.value for m in at.info))
            self.assertEqual(fetched, [])
            for claims in ({"email": "someone@example.com", "email_verified": True},
                           {"email": "owner@example.com", "email_verified": False}):
                user = dict(claims, iss="https://accounts.google.com", sub="7", profile_id="p" * 64)
                with mock.patch("core.accounts.identity", lambda u=user: u), \
                        mock.patch("core.accounts._request", side_effect=OSError("no network in tests")):
                    at.run()
                self.assertTrue(any("not available" in m.value for m in at.info), claims)
                self.assertEqual(fetched, [])
            owner = {"email": "owner@example.com", "email_verified": True, "iss": "https://accounts.google.com", "sub": "8",
                     "profile_id": "o" * 64}
            with mock.patch("core.accounts.identity", lambda: owner), mock.patch("core.accounts.storage_ready", lambda: True), \
                    mock.patch("core.accounts.restore_profile", lambda now=None: None), \
                    mock.patch("core.accounts.save_profile", lambda: None):
                at.run()
                self.assertEqual([t.value for t in at.title], ["Pilot dashboard"])
                self.assertIn("world_explorer_events", fetched)
        self.assertEqual([e.value for e in at.exception], [])


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class GuestToAccountTests(unittest.TestCase):
    """Guest progress kept through Google's sign-in page and added to the account safely."""

    def setUp(self):
        from core import accounts, cookies
        self.accounts, self.cookies = accounts, cookies
        self.accounts._handoffs()["items"].clear()

    def guest_session(self):
        st = fake_st()
        st.session_state.update(points=450, rounds_finished=2, stats={"answered": 10, "correct": 7},
                                records={"best_streak": 4, "scores": {"k1": 450, "k2": 100}},
                                daily={"results": {"2026-10-11": {"correct": 4, "total": 5, "score": 450}},
                                       "streak": 1, "best": 1, "last": "2026-10-11"},
                                mistakes=[{"facts": ["capital:NGA:Abuja"], "country_id": "NGA", "difficulty": "Medium", "kind": "Capitals"}],
                                recent=["NGA"], recent_facts=["capital:NGA:Abuja"])
        with mock.patch.object(self.accounts, "st", st), mock.patch.object(self.cookies, "st", st):
            self.assertTrue(self.accounts.guest_has_progress())
            token = self.accounts.prepare_handoff()
        self.assertEqual(st.session_state.cookie_writes["we_handoff"][0], token)
        return token

    class Table:
        """In-memory stand-in for the profiles table, shared by several sessions (tabs, refreshes)."""

        def __init__(self, profile=None):
            self.profile = profile          # None: no saved row yet
            self.fail_reads = self.fail_writes = False
            self.writes = []

        def request(self, profile_id, payload=None):
            import json
            if payload is None:
                if self.fail_reads:
                    raise OSError("down")
                return [] if self.profile is None else [{"profile": json.loads(json.dumps(self.profile))}]
            if self.fail_writes:
                raise OSError("write failed")
            self.profile = json.loads(json.dumps(payload))
            self.writes.append(self.profile)

    def signed_in_session(self, token, table):
        """A fresh browser session after Google's page (cookie from the guest tab), reading and saving `table`."""
        user = {"iss": "https://accounts.google.com", "sub": "99", "name": "Ada"}
        st = fake_st(secrets={"profiles": STORAGE}, cookies={"we_handoff": token}, user=user)
        from ui import state as ui_state  # defaults for a fresh session after the redirect
        st.session_state.update({k: (list(v) if isinstance(v, list) else v) for k, v in ui_state.DEFAULTS.items()})
        from core import badges, daily, records
        st.session_state.update(stats=badges.empty_stats(), records=records.empty_records(), daily=daily.empty_daily(), mistakes=[])
        self.run_in(st, table, lambda: (self.accounts.restore_profile(now=0), self.accounts.save_profile()))
        return st

    def run_in(self, st, table, fn):
        with mock.patch.object(self.accounts, "st", st), mock.patch.object(self.cookies, "st", st), \
                mock.patch.object(self.accounts, "_request", table.request):
            fn()

    STORED = {"points": 5000, "rounds_finished": 20, "app_language": "Deutsch", "profile_name": "Okey",
              "stats": {"answered": 100, "correct": 80}, "records": {"best_streak": 9, "scores": {"k1": 900}},
              "daily": {"results": {"2026-10-10": {"correct": 5, "total": 5, "score": 900}}, "streak": 6, "best": 6,
                        "last": "2026-10-10"}, "mistakes": []}

    def test_existing_saved_profile_is_added_to_never_replaced(self):
        token = self.guest_session()
        table = self.Table(dict(self.STORED))
        st = self.signed_in_session(token, table)
        ss = st.session_state
        self.assertEqual((ss.points, ss.rounds_finished), (5450, 22))
        self.assertEqual((ss.stats["answered"], ss.stats["correct"]), (110, 87))
        self.assertEqual(ss.records["best_streak"], 9)
        self.assertEqual(ss.records["scores"], {"k1": 900, "k2": 100})          # higher saved record kept
        self.assertEqual((ss.daily["streak"], ss.daily["best"], ss.daily["last"]), (7, 7, "2026-10-11"))
        self.assertEqual(ss.app_language, "Deutsch")                            # saved preferences kept
        self.assertEqual(ss.profile_name, "Okey")
        self.assertEqual(ss.handoff_notice, {"points": 450, "rounds": 2, "existing": True})
        self.assertEqual(len(table.writes), 1)                                   # merged result written once
        self.assertEqual(table.profile["points"], 5450)
        self.assertEqual(len(table.profile["transfers"]), 1)                     # idempotency marker, not the token
        self.assertNotIn(token, str(table.profile))
        self.assertEqual(st.session_state.cookie_writes["we_handoff"], ("", 0))  # token cleared after the save
        self.assertNotIn(token, self.accounts._handoffs()["items"])

    def test_repeated_sign_in_never_adds_twice(self):
        token = self.guest_session()
        table = self.Table(dict(self.STORED))
        self.signed_in_session(token, table)
        st2 = self.signed_in_session(token, table)                      # same old cookie, signs in again
        self.assertEqual(st2.session_state.points, 5450)
        # even if the server still had the guest copy (e.g. a lost clean-up), the saved transfer id blocks it
        items = self.accounts._handoffs()["items"]
        items[token] = {"expires": 9e12, "progress": {"points": 450, "rounds_finished": 2}, "claimed": True}
        st3 = self.signed_in_session(token, table)
        self.assertEqual((st3.session_state.points, table.profile["points"]), (5450, 5450))
        self.assertNotIn(token, items)                                  # cleaned up

    def test_new_account_takes_the_guest_progress(self):
        token = self.guest_session()
        table = self.Table(None)
        st = self.signed_in_session(token, table)
        self.assertEqual((st.session_state.points, st.session_state.rounds_finished), (450, 2))
        self.assertEqual(table.profile["daily"]["results"]["2026-10-11"]["correct"], 4)
        self.assertFalse(st.session_state.handoff_notice["existing"])

    def test_failed_read_keeps_the_hand_off_and_writes_nothing(self):
        token = self.guest_session()
        table = self.Table(dict(self.STORED))
        table.fail_reads = True
        st = self.signed_in_session(token, table)
        self.assertEqual(table.writes, [])
        self.assertEqual(st.session_state.points, 0)
        self.assertIn(token, self.accounts._handoffs()["items"])               # still there for the retry
        table.fail_reads = False
        st2 = self.signed_in_session(token, table)
        self.assertEqual((st2.session_state.points, table.profile["points"]), (5450, 5450))

    def test_failed_save_then_refresh_recovers_exactly_once(self):
        token = self.guest_session()
        table = self.Table(dict(self.STORED))
        table.fail_writes = True
        st = self.signed_in_session(token, table)
        self.assertEqual(table.profile["points"], 5000)                          # nothing half-written
        self.assertIn("pending_transfer", st.session_state)
        self.assertNotIn("handoff_notice", st.session_state)                     # no "saved" message yet
        self.assertTrue(self.accounts._handoffs()["items"][token]["claimed"])    # still recoverable
        self.assertEqual(st.session_state.cookie_writes["we_handoff"][0], token)  # cookie kept for recovery
        table.fail_writes = False
        st2 = self.signed_in_session(token, table)                               # the player refreshes the page
        self.assertEqual((st2.session_state.points, table.profile["points"]), (5450, 5450))
        self.assertNotIn(token, self.accounts._handoffs()["items"])
        # the first tab is still open and retries its pending save: it adopts the saved result, no second add
        self.run_in(st, table, self.accounts.save_profile)
        self.assertEqual((st.session_state.points, table.profile["points"]), (5450, 5450))
        self.assertNotIn("pending_transfer", st.session_state)

    def test_failed_save_recovers_in_the_same_session(self):
        token = self.guest_session()
        table = self.Table(dict(self.STORED))
        table.fail_writes = True
        st = self.signed_in_session(token, table)
        st.session_state.points += 125                                         # keeps playing while offline
        self.run_in(st, table, self.accounts.save_profile)                     # still failing
        table.fail_writes = False
        self.run_in(st, table, self.accounts.save_profile)                     # connection back
        self.assertEqual(table.profile["points"], 5575)                         # 5000 + 450 + 125, guest added once
        self.assertEqual(st.session_state.handoff_notice["points"], 450)
        self.run_in(st, table, self.accounts.save_profile)
        self.assertEqual(len(table.writes), 1)                                  # nothing more to write

    def test_concurrent_tabs_add_guest_progress_once(self):
        token = self.guest_session()
        table = self.Table(dict(self.STORED))
        table.fail_writes = True
        tab_a = self.signed_in_session(token, table)                          # both tabs read before any save
        tab_b = self.signed_in_session(token, table)
        self.assertEqual((tab_a.session_state.points, tab_b.session_state.points), (5450, 5450))
        table.fail_writes = False
        self.run_in(tab_b, table, self.accounts.save_profile)                  # B saves first
        self.run_in(tab_a, table, self.accounts.save_profile)                  # A saves afterwards
        self.assertEqual(table.profile["points"], 5450)
        self.assertEqual(table.profile["rounds_finished"], 22)
        self.assertEqual(table.profile["transfers"], tab_a.session_state.transfers)
        tab_c = self.signed_in_session(token, table)                          # a third tab opened later
        self.assertEqual(tab_c.session_state.points, 5450)

    def test_other_tab_progress_since_load_is_kept_when_merging(self):
        token = self.guest_session()
        table = self.Table(dict(self.STORED))
        table.fail_writes = True
        tab_a = self.signed_in_session(token, table)
        table.fail_writes = False
        table.profile = dict(table.profile, points=5100, rounds_finished=21)  # another device saved meanwhile
        self.run_in(tab_a, table, self.accounts.save_profile)
        self.assertEqual((table.profile["points"], table.profile["rounds_finished"]), (5550, 23))

    def earn(self, st, points=125, rounds=1, answered=5, correct=4):
        """Play while the transfer save is still pending: points, a finished round and answer statistics."""
        ss = st.session_state
        ss.points += points
        ss.rounds_finished += rounds
        ss.stats = dict(ss.stats, answered=ss.stats["answered"] + answered, correct=ss.stats["correct"] + correct)

    def totals(self, profile):
        return (profile["points"], profile["rounds_finished"], profile["stats"]["answered"], profile["stats"]["correct"])

    def test_progress_earned_while_pending_survives_when_another_tab_saved_the_transfer(self):
        token = self.guest_session()
        table = self.Table(dict(self.STORED))                          # 5000 points, 20 rounds, 100/80 answers
        table.fail_writes = True
        tab_a = self.signed_in_session(token, table)
        tab_b = self.signed_in_session(token, table)
        self.earn(tab_a)                                               # A plays on: +125, +1 round, +5/+4 answers
        table.fail_writes = False
        self.run_in(tab_b, table, self.accounts.save_profile)          # B saves the transfer first
        self.assertEqual(self.totals(table.profile), (5450, 22, 110, 87))
        self.run_in(tab_a, table, self.accounts.save_profile)          # A retries: adopts B's save + its own play
        self.assertEqual(self.totals(table.profile), (5575, 23, 115, 91))
        self.assertEqual(self.totals(tab_a.session_state), (5575, 23, 115, 91))
        self.assertEqual(len(table.profile["transfers"]), 1)            # guest progress still counted once

    def test_progress_earned_while_pending_survives_when_the_profile_changed(self):
        token = self.guest_session()
        table = self.Table(dict(self.STORED))
        table.fail_writes = True
        tab_a = self.signed_in_session(token, table)
        self.earn(tab_a)
        table.fail_writes = False
        table.profile = dict(table.profile, points=5100, rounds_finished=21,          # another device saved meanwhile
                             stats={"answered": 105, "correct": 83})
        self.run_in(tab_a, table, self.accounts.save_profile)
        # 5100 saved + 450 guest + 125 earned; 21 + 2 + 1 rounds; 105 + 10 + 5 answered, 83 + 7 + 4 correct
        self.assertEqual(self.totals(table.profile), (5675, 24, 120, 94))
        self.assertEqual(self.totals(tab_a.session_state), (5675, 24, 120, 94))

    def test_failed_retries_after_rebuilding_never_count_twice(self):
        token = self.guest_session()
        table = self.Table(dict(self.STORED))
        table.fail_writes = True
        tab_a = self.signed_in_session(token, table)
        self.earn(tab_a)
        table.profile = dict(table.profile, points=5100, rounds_finished=21, stats={"answered": 105, "correct": 83})
        self.run_in(tab_a, table, self.accounts.save_profile)          # rebuilt on the fresh copy, write fails again
        self.assertEqual(self.totals(tab_a.session_state), (5675, 24, 120, 94))
        self.earn(tab_a, points=25, rounds=0, answered=1, correct=1)   # more play before the connection returns
        self.run_in(tab_a, table, self.accounts.save_profile)          # still failing: nothing counted twice
        table.fail_writes = False
        self.run_in(tab_a, table, self.accounts.save_profile)
        self.assertEqual(self.totals(table.profile), (5700, 24, 121, 95))
        # the same when the other tab's save is the one found on retry
        token2 = self.guest_session()
        table2 = self.Table(dict(self.STORED))
        table2.fail_writes = True
        tab_c = self.signed_in_session(token2, table2)
        tab_d = self.signed_in_session(token2, table2)
        self.earn(tab_c)
        table2.fail_writes = False
        self.run_in(tab_d, table2, self.accounts.save_profile)
        table2.fail_writes = True
        self.run_in(tab_c, table2, self.accounts.save_profile)         # adopts, write fails
        self.earn(tab_c, points=25, rounds=0, answered=1, correct=1)
        table2.fail_writes = False
        self.run_in(tab_c, table2, self.accounts.save_profile)
        self.assertEqual(self.totals(table2.profile), (5600, 23, 116, 92))

    def test_claimed_token_is_never_recreated_by_the_old_guest_tab(self):
        token = self.guest_session()
        table = self.Table(None)
        self.signed_in_session(token, table)                           # claimed and saved
        guest = fake_st()
        guest.session_state.update(handoff_token=token, signin_ready="google", points=450, rounds_finished=2)
        with mock.patch.object(self.accounts, "st", guest), mock.patch.object(self.cookies, "st", guest):
            self.accounts.refresh_handoff()                         # end of a run in the old guest tab
        self.assertNotIn(token, self.accounts._handoffs()["items"])
        self.assertNotIn("handoff_token", guest.session_state)
        st2 = self.signed_in_session(token, table)
        self.assertEqual(st2.session_state.points, 450)               # not added a second time

    def test_old_guest_tab_cannot_change_a_claimed_transfer(self):
        token = self.guest_session()
        table = self.Table(None)
        table.fail_writes = True
        self.signed_in_session(token, table)                           # claimed, save pending
        guest = fake_st()
        guest.session_state.update(handoff_token=token, points=9999, rounds_finished=50)
        with mock.patch.object(self.accounts, "st", guest), mock.patch.object(self.cookies, "st", guest):
            self.accounts.refresh_handoff()
        self.assertEqual(self.accounts._handoffs()["items"][token]["progress"]["points"], 450)

    def test_expired_or_unknown_token_is_ignored(self):
        token = self.guest_session()
        items = self.accounts._handoffs()["items"]
        items[token]["expires"] = 0
        table = self.Table({"points": 10})
        st = self.signed_in_session(token, table)
        self.assertEqual(st.session_state.points, 10)
        st = self.signed_in_session("x" * 32, table)
        self.assertEqual(st.session_state.points, 10)

    def test_invitation_after_first_round_prepares_the_hand_off(self):
        logins = []
        with mock.patch("core.accounts.provider_ready", lambda p: True), \
                mock.patch("core.accounts.login", lambda p: logins.append(p) or True):
            at = AppTest.from_file(APP, default_timeout=60).run()
            self.assertEqual([b for b in at.button if b.key == "save_invite_google"], [])   # not before a round
            at.button(key="explore_daily").click().run()
            for i in range(5):
                q = at.session_state["quiz"]
                qn = q["questions"][i]
                at.button(key=f"answer_{q['serial']}_{i}_{qn['choices'].index(qn['answer'])}").click().run()
                at.button(key=f"next_{q['serial']}_{i}").click().run()
            self.assertEqual(at.button(key="save_invite_google").label, "Save your progress with Google")
            at.button(key="save_invite_google").click().run()                  # step 1: keep progress for the account
            token = at.session_state["handoff_token"]
            self.assertIn(token, self.accounts._handoffs()["items"])
            self.assertEqual(self.accounts._handoffs()["items"][token]["progress"]["rounds_finished"], 1)
            self.assertEqual(logins, [])
            at.button(key="save_invite_google_go").click().run()               # step 2: off to Google
            self.assertEqual(logins, ["google"])
            at2 = AppTest.from_file(APP, default_timeout=60).run()
            at2.button(key="explore_daily").click().run()
            for i in range(5):
                q = at2.session_state["quiz"]
                qn = q["questions"][i]
                at2.button(key=f"answer_{q['serial']}_{i}_{qn['choices'].index(qn['answer'])}").click().run()
                at2.button(key=f"next_{q['serial']}_{i}").click().run()
            at2.button(key="save_invite_dismiss").click().run()                # "Continue as guest"
            self.assertEqual([b for b in at2.button if b.key == "save_invite_google"], [])
            self.assertEqual([e.value for e in list(at.exception) + list(at2.exception)], [])

    def test_merge_continues_saved_streak_without_lowering_it(self):
        saved = {"points": 0, "rounds_finished": 0, "stats": {}, "records": {}, "recent": [], "recent_facts": [],
                 "mistakes": [], "daily": {"results": {"2026-10-10": {"correct": 1, "total": 5, "score": 1}},
                                           "streak": 70, "best": 70, "last": "2026-10-10"}}
        guest = {"daily": {"results": {"2026-10-09": {"correct": 5, "total": 5, "score": 9},
                                       "2026-10-11": {"correct": 2, "total": 5, "score": 2}}, "streak": 1, "best": 2, "last": "2026-10-11"}}
        out = self.accounts.merge_progress(saved, guest)
        self.assertEqual((out["daily"]["streak"], out["daily"]["best"]), (71, 71))
        self.assertEqual(out["daily"]["results"]["2026-10-10"]["correct"], 1)  # saved day keeps its saved result
        self.assertEqual(out["daily"]["results"]["2026-10-09"]["correct"], 5)


if __name__ == "__main__":
    unittest.main()


class InterfaceTextTests(unittest.TestCase):
    def test_every_interface_string_has_translations(self):
        """Every literal passed to t()/e() in the interface has German, Spanish and Chinese text
        (the owner dashboard is English-only by design)."""
        import ast
        import json
        strings = json.loads((ROOT / "data" / "translations.json").read_text(encoding="utf-8"))["strings"]
        missing = []
        for path in list((ROOT / "ui").glob("*.py")) + [ROOT / "app.py"]:
            if path.name == "owner.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                func = getattr(node, "func", None)
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if isinstance(node, ast.Call) and name in ("t", "e") and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value not in strings:
                        missing.append(f"{path.name}:{node.lineno} {arg.value[:60]}")
        self.assertEqual(missing, [])
