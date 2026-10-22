"""Country photographs: dataset rules, verified attribution, responsive loading and the fallback."""
import json
import sys
import unittest
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
            self.assertEqual(rec["url"], photos.original_url(name), cid)
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


@unittest.skipIf(AppTest is None, "streamlit is not installed")
class PageTests(unittest.TestCase):
    def new(self, **state):
        at = AppTest.from_file(APP, default_timeout=60)
        for k, v in state.items():
            at.session_state[k] = v
        return at.run()

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
        with mock.patch.object(urllib.request, "urlopen", side_effect=self.commons_reply):
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
        with mock.patch.object(urllib.request, "urlopen", side_effect=OSError("offline")):
            at = self.new(explore_selected="South America", explore_country="PER")   # not verified, Commons unreachable
        self.assertFalse(any("photo-frame" in m.value for m in at.markdown if "<figure" in m.value))
        self.assertTrue(any('class="learn-map detail-locator"' in m.value for m in at.markdown))

    def test_country_list_is_alphabetical(self):
        at = self.new(explore_selected="Africa")
        rows = [b.key.removeprefix("discover_") for b in at.button if b.key and b.key.startswith("discover_")]
        from core.data import get_country
        names = [get_country(r)["name"] for r in rows]
        self.assertEqual(names, sorted(names))
        self.assertEqual(rows[0], "DZA")        # Algeria, no longer the photo countries first


if __name__ == "__main__":
    unittest.main()
