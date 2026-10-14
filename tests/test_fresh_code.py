"""After a deploy the running app must use the new Python code, and never mix old markup with a new stylesheet."""
import ast
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _guard():
    """Load _load_fresh_code() from app.py without running the app."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_load_fresh_code")
    ns = {"__file__": str(ROOT / "app.py")}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "app.py", "exec"), ns)
    return ns["_load_fresh_code"]


class FreshCodeTests(unittest.TestCase):
    def setUp(self):
        self.saved = getattr(sys, "_world_explorer_code_stamp", None)

    def tearDown(self):
        sys._world_explorer_code_stamp = self.saved
        for name in ("ui.fake_stale_module",):
            sys.modules.pop(name, None)

    def _fake_module(self):
        mod = types.ModuleType("ui.fake_stale_module")
        mod.__file__ = str(ROOT / "ui" / "fake_stale_module.py")
        sys.modules["ui.fake_stale_module"] = mod

    def test_guard_runs_before_project_imports(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertLess(src.index("\n_load_fresh_code()"), src.index("from core import"))
        self.assertLess(src.index("\n_load_fresh_code()"), src.index("from ui.components import"))

    def test_unchanged_code_keeps_loaded_modules(self):
        guard = _guard()
        sys._world_explorer_code_stamp = None
        guard()
        self._fake_module()
        guard()
        self.assertIn("ui.fake_stale_module", sys.modules)

    def test_changed_code_drops_project_modules_only(self):
        guard = _guard()
        sys._world_explorer_code_stamp = None
        guard()
        self._fake_module()
        sys._world_explorer_code_stamp = (("changed", 0, 0),)  # as if a deploy replaced the files
        guard()
        self.assertNotIn("ui.fake_stale_module", sys.modules)
        self.assertIn("pathlib", sys.modules)  # other modules are never touched
        self.assertIn("unittest", sys.modules)

    def test_stylesheet_follows_running_code(self):
        src = (ROOT / "ui" / "components.py").read_text(encoding="utf-8")
        self.assertIn('html(f"<style>{_current_stylesheet()}</style>")', src)
        self.assertIn("return _CSS_AT_IMPORT", src)
        self.assertIn("UI_BUILD", src)


if __name__ == "__main__":
    unittest.main()
