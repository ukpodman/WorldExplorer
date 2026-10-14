"""The phone privacy notice must still explain what is being collected, in every language."""
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHORT = "Allow anonymous usage statistics. No names, emails or answers."


class ConsentTextTests(unittest.TestCase):
    def test_short_explanation_translated_in_all_languages(self):
        data = json.loads((ROOT / "data" / "translations.json").read_text(encoding="utf-8"))
        row = data["strings"].get(SHORT)
        self.assertIsNotNone(row)
        self.assertEqual(len(row), len(data["strings"]["Help improve World Explorer?"]))
        self.assertTrue(all(text.strip() and text != SHORT for text in row))

    def test_phone_css_shows_short_text_and_desktop_keeps_full_text(self):
        css = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".consent-text .consent-short { display:inline; }", css)
        self.assertIn(".consent-text .consent-full { display:none; }", css)
        src = (ROOT / "ui" / "components.py").read_text(encoding="utf-8")
        self.assertIn('class="consent-short"', src)
        self.assertIn('class="consent-full"', src)


if __name__ == "__main__":
    unittest.main()
