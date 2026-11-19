import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class ShowdownBuildTests(unittest.TestCase):
    def test_offline_build_reuses_classic_replay_without_rewriting_it(self):
        source = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("build_demo.py", "demo.html"):
                shutil.copyfile(source / name, root / name)
            classic = (root / "demo.html").read_bytes()
            (root / "showdown-ui.html").write_text("<!--SHOWDOWN_DATA-->\n<!--SHOWDOWN_CORE-->")
            (root / "showdown-core.js").write_text("const demo = true;")
            subprocess.run([sys.executable, "-B", "build_demo.py", "--showdown"], check=True,
                           cwd=root, env={**os.environ, "PYTHONPATH": str(source)})
            page = (root / "showdown.html").read_text()
            self.assertEqual((root / "demo.html").read_bytes(), classic)
            self.assertIn("<script>const demo = true;</script>", page)
            opening = '<script type="application/json" id="recorded-runs">'
            payload = classic.decode().split(opening, 1)[1].split("</script>", 1)[0]
            self.assertIn(opening + payload + "</script>", page)
