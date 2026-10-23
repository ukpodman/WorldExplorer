"""Country photographs: dataset rules, verified attribution, responsive loading and the fallback."""
import json
import sys
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import photos  # noqa: E402

try:
    from streamlit.testing.v1 import AppTest
except ImportError:  # pragma: no cover
    AppTest = None

APP = str(ROOT / "app.py")
META = {"author": "A. Photographer", "license": "CC BY-SA 4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0",
        "url": "https://upload.wikimedia.org/wikipedia/commons/x/xy/X.jpg", "page": "https://commons.wikimedia.org/wiki/File:X.jpg",
        "width": 4000, "height": 2667}


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.records = photos.load_records()
        self.countries = {c["id"] for c in json.loads((ROOT / "data" / "countries.json").read_text(encoding="utf-8"))}

    def test_at_least_twenty_countries_with_file_and_caption(self):
        self.assertGreaterEqual(len(self.records), 20)
        for cid, rec in self.records.items():
            self.assertIn(cid, self.countries, cid)
            self.assertTrue(rec["file"].startswith("File:") and rec["caption"], cid)

    def test_urls_are_derived_from_the_commons_file_name(self):
        for cid, rec in self.records.items():
            name = photos.file_name(rec)
            # Commons writes ',' '(' ')' "'" literally where we percent-encode them; both reach the same file
            self.assertEqual(urllib.parse.unquote(rec["url"]), urllib.parse.unquote(photos.original_url(name)), cid)
            self.assertTrue(rec["page"].startswith("https://commons.wikimedia.org/wiki/File:"), cid)

    def test_credits_are_never_partial(self):
        """A record either has a photographer and an allowed licence, or no credit fields at all (Commons fills them)."""
        for cid, rec in self.records.items():
            if rec.get("author") or rec.get("license"):
                self.assertTrue(photos.complete(rec), cid)

    def test_known_commons_path(self):
        self.assertEqual(photos.original_url("Lekki_Ikoyi_Link_Bridge.jpg"),
                         "https://upload.wikimedia.org/wikipedia/commons/7/74/Lekki_Ikoyi_Link_Bridge.jpg")


class ResolveTests(unittest.TestCase):
    def setUp(self):
        photos._cache.clear()

    def test_unverified_record_takes_credits_from_commons(self):
        rec = {"file": "File:X.jpg", "caption": "Somewhere"}
        out = photos.resolve(rec, fetch=lambda names: {"X.jpg": dict(META)})
        self.assertEqual((out["author"], out["license"], out["caption"]), ("A. Photographer", "CC BY-SA 4.0", "Somewhere"))
        src, srcset = photos.sources(out)
        self.assertIn("/thumb/", src)
        self.assertIn("960px-X.jpg", src)
        self.assertEqual([part.split()[-1] for part in srcset.split(", ")], ["330w", "500w", "960w", "1280w"])

    def test_disallowed_or_missing_licence_is_not_shown(self):
        for lic in ("", "Copyrighted", "CC BY-NC 4.0", "All rights reserved"):
            photos._cache.clear()
            meta = dict(META, license=lic)
            self.assertIsNone(photos.resolve({"file": "File:X.jpg", "caption": "c"}, fetch=lambda n, m=meta: {"X.jpg": m}), lic)

    def test_no_photographer_is_not_shown(self):
        self.assertIsNone(photos.resolve({"file": "File:X.jpg", "caption": "c"}, fetch=lambda n: {"X.jpg": dict(META, author="")}))

    def test_network_failure_falls_back_and_is_retried_later(self):
        calls = []

        def broken(names):
            calls.append(names)
            raise OSError("offline")
        self.assertIsNone(photos.resolve({"file": "File:X.jpg", "caption": "c"}, fetch=broken))
        self.assertIsNone(photos.resolve({"file": "File:X.jpg", "caption": "c"}, fetch=broken))
        self.assertEqual(len(calls), 1, "a failure is cached briefly, not retried on every rerun")
        credited = {"file": "File:Y.jpg", "caption": "c", "author": "B", "license": "CC0", "url": "https://upload.wikimedia.org/y.jpg",
                    "page": "https://commons.wikimedia.org/wiki/File:Y.jpg"}
        self.assertEqual(photos.resolve(credited, fetch=broken)["author"], "B")   # recorded credits still work offline

    def test_verified_records_need_no_network(self):
        rec = {"file": "File:X.jpg", "caption": "c", "verified": "2026-10-22", **META}
        self.assertIs(photos.resolve(rec, fetch=mock.Mock(side_effect=AssertionError("no lookup"))), rec)

    def test_hand_recorded_credits_stay(self):
        rec = {"file": "File:X.jpg", "caption": "c", "author": "Chippla", "license": "CC BY-SA 3.0",
               "license_url": "https://creativecommons.org/licenses/by-sa/3.0/", "page": META["page"], "url": META["url"]}
        out = photos.resolve(rec, fetch=lambda n: {"X.jpg": dict(META)})
        self.assertEqual((out["author"], out["license"], out["width"]), ("Chippla", "CC BY-SA 3.0", 4000))

    def test_small_originals_are_not_upscaled(self):
        self.assertEqual(photos.sources({"file": "File:X.jpg", "url": "https://u/x.jpg", "width": 300}), ("https://u/x.jpg", ""))
        src, srcset = photos.sources({"file": "File:X.jpg", "width": 800})
        self.assertIn("500px-X.jpg", src)
        self.assertNotIn("960w", srcset)

    def test_html_is_stripped_from_commons_values(self):
        self.assertEqual(photos._plain('<a href="//commons.wikimedia.org/wiki/User:A">A &amp; B</a>'), "A & B")


def _tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location("photo_credits", ROOT / "tools" / "photo_credits.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _meta(name, w=4000, h=2667, lic="CC BY-SA 4.0", author="A. Photographer"):
    return {"author": author, "license": lic, "license_url": "https://creativecommons.org/licenses/by-sa/4.0",
            "url": photos.original_url(name), "page": photos.page_url(name), "width": w, "height": h}


class CandidateTests(unittest.TestCase):
    """tools/photo_candidates.json: one hand-picked list per remaining state, checked by tools/photo_credits.py."""

    @classmethod
    def setUpClass(cls):
        cls.tool = _tool()
        cls.cands = cls.tool.load_candidates()
        cls.records = photos.load_records()
        from core.data import STATES
        cls.states = {c["id"] for c in STATES}

    def test_records_and_candidates_together_cover_all_195_states_once(self):
        add = self.cands["add"]
        self.assertEqual(len(self.states), 195)
        self.assertLessEqual(set(add), self.states)                       # every candidate is a real state
        self.assertEqual(set(add) | set(self.records), self.states)        # holds for 20 records and for 191
        self.assertEqual(set(self.cands["landscape_review"]), {"FRA", "ITA", "USA"})

    def test_every_candidate_names_its_country_a_caption_and_commons_files(self):
        from core.data import get_country
        for cid, entry in {**self.cands["add"], **self.cands["landscape_review"]}.items():
            self.assertEqual(entry["country"], get_country(cid)["name"], cid)
            self.assertTrue(entry["caption"].strip(), cid)
            self.assertTrue(1 <= len(entry["files"]) == len(set(entry["files"])), cid)
            for f in entry["files"]:
                self.assertTrue(f.startswith("File:") and f.lower().endswith((".jpg", ".jpeg", ".png")), (cid, f))
                self.assertNotIn("banner", f.lower(), (cid, f))      # Wikivoyage banners are too wide to frame

    def test_add_uses_the_first_candidate_that_passes_and_stores_full_metadata(self):
        entry = {"country": "Testland", "caption": "A view", "files": ["File:Tall.jpg", "File:Nc.jpg", "File:Small.jpg", "File:Good.jpg"]}
        found = {"Tall.jpg": _meta("Tall.jpg", 2000, 3000), "Nc.jpg": _meta("Nc.jpg", lic="CC BY-NC 4.0"),
                 "Small.jpg": _meta("Small.jpg", 800, 500), "Good.jpg": _meta("Good.jpg")}
        records = {}
        log = self.tool.add_from_candidates(records, {"add": {"TST": entry}}, fetch=lambda names: found, today="2026-10-23")
        rec = records["TST"]
        self.assertEqual(rec["file"], "File:Good.jpg")
        for key in ("country", "caption", "author", "license", "license_url", "url", "page", "width", "height", "attribution"):
            self.assertTrue(rec.get(key), key)
        self.assertEqual(rec["verified"], "2026-10-23")
        self.assertTrue(self.tool.verified(rec))
        self.assertIn("TST: added Good.jpg", log[0])

    def test_per_file_captions_and_frame_limits(self):
        for cid, entry in {**self.cands["add"], **self.cands["landscape_review"]}.items():
            self.assertLessEqual(set(entry.get("captions", {})), set(entry["files"]), cid)
        entry = {"caption": "Default", "files": ["File:Pano.jpg", "File:Mid.jpg", "File:Alt.jpg"],
                 "captions": {"File:Alt.jpg": "Its own caption"}}
        found = {"Pano.jpg": _meta("Pano.jpg", 9000, 1500), "Mid.jpg": _meta("Mid.jpg", 1100, 700), "Alt.jpg": _meta("Alt.jpg")}
        rec, reasons = self.tool.choose("TST", entry, found, "2026-10-23")
        self.assertEqual((rec["file"], rec["caption"]), ("File:Alt.jpg", "Its own caption"))
        self.assertIn("too wide", reasons[0])
        rec, _ = self.tool.choose("TST", entry, found, "2026-10-23", min_width=1024)   # the --min-width last resort
        self.assertEqual((rec["file"], rec["caption"]), ("File:Mid.jpg", "Default"))

    def test_incomplete_commons_metadata_is_skipped_without_crashing(self):
        """Regression (KeyError: 'author'): bad candidates are rejected with a reason and the next one is tried."""
        good = _meta("Good.jpg")
        no_author = {k: v for k, v in _meta("NoAuthor.jpg").items() if k != "author"}
        no_licence = {k: v for k, v in _meta("NoLicence.jpg").items() if k not in ("license", "license_url")}
        nones = dict(_meta("Nones.jpg"), author=None, license=None)
        bare = {"url": photos.original_url("Bare.jpg")}                          # no author, licence or size at all
        no_size = {k: v for k, v in _meta("NoSize.jpg").items() if k not in ("width", "height")}
        found = {"NoAuthor.jpg": no_author, "NoLicence.jpg": no_licence, "Nones.jpg": nones, "Bare.jpg": bare,
                 "NoSize.jpg": no_size, "Good.jpg": good}
        entry = {"caption": "c", "files": ["File:" + n for n in found]}
        rec, reasons = self.tool.choose("TST", entry, found, "2026-10-23")
        self.assertEqual(rec["file"], "File:Good.jpg")
        self.assertEqual(rec["attribution"], "A. Photographer · CC BY-SA 4.0 · via Wikimedia Commons")
        self.assertEqual(len(reasons), 5)
        for name in ("NoAuthor", "NoLicence", "Nones", "Bare"):
            self.assertTrue(any(r.startswith(name) and "not allowed" in r for r in reasons), name)
        self.assertTrue(any(r.startswith("NoSize") and "px wide" in r for r in reasons))
        # all candidates bad → no record, no exception, reported
        records = {}
        log = self.tool.add_from_candidates(records, {"add": {"TST": {"caption": "c", "files": ["File:NoAuthor.jpg", "File:Bare.jpg"]}}},
                                            fetch=lambda names: found, today="2026-10-23")
        self.assertEqual(records, {})
        self.assertIn("UNRESOLVED", log[0])

    def test_attribution_never_raises(self):
        self.assertEqual(self.tool.attribution({}), "")
        self.assertEqual(self.tool.attribution({"author": "A", "license": None}), "")
        self.assertEqual(self.tool.attribution({"author": " ", "license": "CC0"}), "")
        self.assertEqual(self.tool.attribution({"author": "A", "license": "CC0"}), "A · CC0 · via Wikimedia Commons")

    def test_refresh_handles_records_without_credits(self):
        records = {"TST": {"file": "File:NoAuthor.jpg", "caption": "c"}}
        meta = {k: v for k, v in _meta("NoAuthor.jpg").items() if k != "author"}
        log = self.tool.refresh(records, everything=True, fetch=lambda names: {"NoAuthor.jpg": meta})
        self.assertIn("NOT shown", log[0])
        self.assertNotIn("verified", records["TST"])

    def test_unresolved_country_gets_no_record_and_is_reported(self):
        records = {}
        log = self.tool.add_from_candidates(records, {"add": {"TST": {"caption": "c", "files": ["File:Gone.jpg"]}}},
                                            fetch=lambda names: {}, today="2026-10-23")
        self.assertEqual(records, {})
        self.assertIn("UNRESOLVED", log[0])

    def test_verified_records_are_never_overwritten_and_landscape_review_keeps_the_old_metadata(self):
        old = {"file": "File:Old.jpg", "caption": "Old", "verified": "2026-10-22", **_meta("Old.jpg", 2000, 3000)}
        keep = {"file": "File:Keep.jpg", "caption": "Keep", "verified": "2026-10-22", **_meta("Keep.jpg")}
        records = {"FRA": dict(old), "KEP": dict(keep)}
        found = {"New.jpg": _meta("New.jpg")}
        cands = {"add": {"KEP": {"caption": "x", "files": ["File:New.jpg"]}},
                 "landscape_review": {"FRA": {"caption": "Mont", "files": ["File:New.jpg"]}}}
        self.tool.add_from_candidates(records, cands, fetch=lambda names: found, today="2026-10-23")
        self.assertEqual(records["KEP"], keep)                       # --add leaves verified records alone
        self.assertEqual(records["FRA"], dict(old))                  # no --landscape: unchanged
        self.tool.add_from_candidates(records, cands, fetch=lambda names: found, landscape_review=True, today="2026-10-23")
        self.assertEqual(records["FRA"]["file"], "File:New.jpg")
        self.assertEqual(records["FRA"]["previous"]["file"], "File:Old.jpg")
        self.assertEqual(records["FRA"]["previous"]["author"], old["author"])

    def test_coverage_counts_only_verified_states_and_never_claims_completion_early(self):
        good = {"file": "File:G.jpg", "caption": "c", "verified": "2026-10-23", **_meta("G.jpg")}
        cov = self.tool.coverage({"NGA": good, "GHA": {"file": "File:H.jpg", "caption": "c"}}, {"NGA", "GHA", "KEN"})
        self.assertEqual((cov["verified"], cov["pending"], cov["missing"]), (["NGA"], ["GHA"], ["KEN"]))
        lines = self.tool.summary_lines(cov)
        self.assertEqual(lines[0], "Coverage: 1/3 states have a verified photograph record")
        self.assertFalse(any("All states verified" in line for line in lines))

    def test_url_check_reports_failures_without_stopping(self):
        good = {"file": "File:G.jpg", "caption": "c", "verified": "2026-10-23", **_meta("G.jpg")}

        def opener(req, timeout):
            raise OSError("offline")
        bad = self.tool.check_urls({"NGA": good}, opener=opener, sleep=lambda s: None)
        self.assertEqual(len(bad), 1)
        self.assertIn("/thumb/", bad[0])
        self.assertIn("network error (OSError)", bad[0])

    def _fake(self, script):
        """An opener answering each URL from a list of statuses (popped in order); records every request."""
        import io
        calls = []

        def opener(req, timeout):
            calls.append((req.get_method(), req.full_url, dict(req.header_items())))
            status, headers = script[req.full_url].pop(0) if isinstance(script[req.full_url][0], tuple) else (script[req.full_url].pop(0), {})
            if status >= 400:
                raise urllib.error.HTTPError(req.full_url, status, "x", headers, io.BytesIO())
            resp = io.BytesIO()
            resp.status = status
            resp.__enter__, resp.__exit__ = (lambda: resp), (lambda *a: False)
            return resp
        return opener, calls

    def _rec(self, name):
        return {"file": "File:" + name, "caption": "c", "verified": "2026-10-23", **_meta(name)}

    def test_url_check_retries_rate_limiting_and_paces_requests(self):
        a, b = self._rec("A.jpg"), self._rec("B.jpg")
        script = {photos.sources(a)[0]: [(429, {"Retry-After": "7"}), 200], photos.sources(b)[0]: [200]}
        opener, calls = self._fake(script)
        waits = []
        bad = self.tool.check_urls({"AAA": a, "BBB": b}, opener=opener, sleep=waits.append, delay=1.5)
        self.assertEqual(bad, [])
        self.assertEqual(waits, [7.0, 1.5])                  # Retry-After honoured, then the pause between countries
        self.assertTrue(all(h.get("User-agent") == photos.USER_AGENT for _, _, h in calls))

    def test_url_check_explains_persistent_throttling_404s_and_head_refusal(self):
        lim, gone, thumb, head = (self._rec(n) for n in ("Lim.jpg", "Gone.jpg", "Thumb.jpg", "Head.jpg"))
        script = {photos.sources(lim)[0]: [429] * 4,
                  photos.sources(gone)[0]: [404], gone["url"]: [404],
                  photos.sources(thumb)[0]: [404], thumb["url"]: [200],
                  photos.sources(head)[0]: [405, 206]}
        opener, calls = self._fake(script)
        bad = self.tool.check_urls({"LIM": lim, "GON": gone, "THU": thumb, "HEA": head}, opener=opener, sleep=lambda s: None)
        text = "\n".join(bad)
        self.assertEqual(len(bad), 3)                        # HEAD refused → GET with Range succeeded
        self.assertIn("LIM: 429 · rate-limited", text)
        self.assertIn("GON: 404 · file not found on Commons", text)
        self.assertIn("THU: 404 · thumbnail not available, but the original file exists", text)
        self.assertIn(("GET", photos.sources(head)[0]), [(m, u) for m, u, _ in calls])
        self.assertIn("rate limiting (429)", "\n".join(self.tool.url_summary(bad)))

    def test_url_check_only_selected_countries(self):
        a, b = self._rec("A.jpg"), self._rec("B.jpg")
        opener, calls = self._fake({photos.sources(b)[0]: [200]})
        self.assertEqual(self.tool.check_urls({"AAA": a, "BBB": b}, opener=opener, sleep=lambda s: None, only={"BBB"}), [])
        self.assertEqual(len(calls), 1)

    def test_commons_style_urls_are_not_reported_as_mismatched(self):
        name = "Krak_des_Chevaliers,_NW_Syria_(3).jpg"
        literal = "https://upload.wikimedia.org/wikipedia/commons/" + photos._hash_path(name) + "/" + name
        rec = {"file": "File:" + name, "caption": "c", **_meta(name), "url": literal}
        self.assertFalse(any("does not match" in p for p in self.tool.check({"SYR": rec}, {"SYR"})))

    def test_offline_check_flags_mismatched_urls(self):
        rec = {"file": "File:G.jpg", "caption": "c", **_meta("G.jpg"), "url": "https://example.org/other.jpg"}
        self.assertTrue(any("does not match" in p for p in self.tool.check({"NGA": rec}, {"NGA"})))


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class PageTests(unittest.TestCase):
    def new(self, **state):
        at = AppTest.from_file(APP, default_timeout=60)
        for k, v in state.items():
            at.session_state[k] = v
        return at.run()

    @staticmethod
    def unverified_peru():
        """Peru as a record without stored credits, whatever data/photos.json holds (20 or 195 verified records)."""
        import core.data
        return mock.patch.dict(core.data.PHOTO_RECORDS, {"PER": {"file": "File:Machu_Picchu,_Peru.jpg",
                                                                 "caption": "Machu Picchu, Cusco Region"}})

    def test_verified_record_is_shown_as_stored_without_network(self):
        import core.data
        import urllib.request
        rec = {"file": "File:Machu_Picchu,_Peru.jpg", "caption": "Machu Picchu, Cusco Region", **META,
               "width": 1600, "height": 1067, "verified": "2026-10-23"}
        with mock.patch.dict(core.data.PHOTO_RECORDS, {"PER": rec}), \
                mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("no lookup for verified records")):
            at = self.new(explore_selected="South America", explore_country="PER")
        figure = next(m.value for m in at.markdown if 'class="photo-frame detail-photo-frame"' in m.value)
        for part in ('width="1600" height="1067"', "aspect-ratio:1600/1067", "960px-", "A. Photographer", "CC BY-SA 4.0"):
            self.assertIn(part, figure)
        self.assertEqual([e.value for e in at.exception], [])

    @staticmethod
    def commons_reply(*args, **kwargs):
        """What the Commons API returns for Machu_Picchu,_Peru.jpg (patched at urllib level, so it also reaches a
        freshly reloaded core.photos module)."""
        import io
        body = {"query": {"pages": [{"title": "File:Machu Picchu, Peru.jpg", "imageinfo": [{
            "url": META["url"], "descriptionurl": META["page"], "width": 4000, "height": 2667,
            "extmetadata": {"Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:A">A. Photographer</a>'},
                            "LicenseShortName": {"value": "CC BY-SA 4.0"}, "LicenseUrl": {"value": META["license_url"]}}}]}]}}
        reply = io.BytesIO(json.dumps(body).encode())
        reply.__enter__, reply.__exit__ = (lambda: reply), (lambda *a: False)
        return reply

    def test_photo_with_credit_and_proportions_in_the_detail_panel(self):
        import urllib.request
        for module in [m for name, m in sys.modules.items() if name == "core.photos"]:
            module._cache.clear()
        with mock.patch.object(urllib.request, "urlopen", side_effect=self.commons_reply), self.unverified_peru():
            at = self.new(explore_selected="South America", explore_country="PER")
        figure = next(m.value for m in at.markdown if 'class="photo-frame detail-photo-frame"' in m.value)
        for part in ('width="4000" height="2667"', 'aspect-ratio:4000/2667', 'loading="lazy"', 'srcset="', "sizes=",
                     "Machu Picchu, Cusco Region", "A. Photographer", "CC BY-SA 4.0", "Wikimedia Commons"):
            self.assertIn(part, figure)
        self.assertEqual([e.value for e in at.exception], [])

    def test_missing_photo_shows_the_locator_map(self):
        import urllib.request
        for module in [m for name, m in sys.modules.items() if name == "core.photos"]:
            module._cache.clear()
        with mock.patch.object(urllib.request, "urlopen", side_effect=OSError("offline")), self.unverified_peru():
            at = self.new(explore_selected="South America", explore_country="PER")   # not verified, Commons unreachable
        self.assertFalse(any("photo-frame" in m.value for m in at.markdown if "<figure" in m.value))
        self.assertTrue(any('class="learn-map detail-locator"' in m.value for m in at.markdown))

    def test_learn_counter_names_the_continent_filter_and_one_navigation_row(self):
        at = self.new(page="Learn", learn_continent="Africa", learn_continent_pick="Africa", learn_country="NGA")
        self.assertTrue(any("· Africa" in c.value for c in at.caption), [c.value for c in at.caption])
        keys = [b.key for b in at.button]
        self.assertIn("learn_next_top", keys)
        self.assertNotIn("learn_next_bottom", keys)                   # no duplicate navigation under the card
        self.assertTrue(any('class="learn-intro"' in m.value and "bordered by 4 countries" in m.value for m in at.markdown))

    def test_country_list_is_alphabetical(self):
        at = self.new(explore_selected="Africa")
        rows = [b.key.removeprefix("discover_") for b in at.button if b.key and b.key.startswith("discover_")]
        from core.data import get_country
        names = [get_country(r)["name"] for r in rows]
        self.assertEqual(names, sorted(names))
        self.assertEqual(rows[0], "DZA")        # Algeria, no longer the photo countries first


if __name__ == "__main__":
    unittest.main()
