"""The phone's copies (web/app.js GET_CACHE): every write route and every saved setting says which copies it drops.
One that isn't listed still works (it drops every copy) but makes every other page wait on the network once."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "web" / "app.js").read_text()
APP_PY = (ROOT / "sog" / "app.py").read_text()


def _keys(name: str) -> set[str]:
    block = re.search(r"const %s = \{(.*?)\n\};" % name, APP_JS, re.S).group(1)
    return set(re.findall(r'"?([\w/]+)"?:', block))


def test_every_write_route_is_listed():
    listed = _keys("WRITE_DROPS")
    writes = re.findall(r'@app\.(?:post|put|delete)\("(/api/[^"]*)"', APP_PY)
    own = {"/api/settings", "/api/views"}   # settings: dropped per changed field; views: a beacon, not through api()
    missing = [w for w in writes if w not in own and not any(w == k or w.startswith(k + "/") for k in listed)]
    assert not missing, f"add these to WRITE_DROPS in web/app.js: {missing}"


def test_every_setting_is_listed():
    fields = set(re.findall(r'^\s+"(\w+)":', APP_PY.split('@app.put("/api/settings")')[1].split("store.save_settings")[0], re.M))
    assert fields and fields <= _keys("SETTING_DROPS"), f"add to SETTING_DROPS in web/app.js: {fields - _keys('SETTING_DROPS')}"
