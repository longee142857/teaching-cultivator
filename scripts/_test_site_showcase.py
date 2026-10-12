# -*- coding: utf-8 -*-
"""Static showcase: bilingual copy, relative Pages paths, no secrets."""
from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
PAGES = ("index.html", "product.html", "gallery.html", "how.html", "contact.html")
FORBIDDEN = (
    "PRACTICE_API_TOKEN",
    "DINGTALK_",
    "X-Learner-Id",
    "Bearer ",
    "client_secret",
    "api_key",
    "conversation_id",
    ".env",
    "sk-",
    "04022300566420984205",
)

_fails = 0


def fail(msg: str) -> None:
    global _fails
    _fails += 1
    print("FAIL", msg)


def load_strings() -> dict:
    script = r"""
const fs = require("fs");
const vm = require("vm");
const context = {
  console,
  localStorage: { getItem() { return null; }, setItem() {} },
  CustomEvent: function CustomEvent() {},
  document: {
    documentElement: {
      lang: "zh-CN",
      getAttribute() { return "zh-CN"; },
      setAttribute() {},
    },
    readyState: "loading",
    addEventListener() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    body: { addEventListener() {}, getAttribute() { return null; } },
    dispatchEvent() {},
  },
};
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync("site/js/i18n.js", "utf8"), context);
const STR = context.TC.STR;
const keys = Object.keys(STR.zh);
if (keys.length !== Object.keys(STR.en).length) process.exit(2);
for (const key of keys) {
  if (!(key in STR.en)) process.exit(3);
  if (!STR.zh[key] || !STR.en[key]) process.exit(4);
  if (STR.zh[key] === STR.en[key]) process.exit(5);
}
process.stdout.write(JSON.stringify(STR));
"""
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        fail("i18n parity node exit %s\n%s" % (proc.returncode, proc.stderr or proc.stdout))
        return {"zh": {}, "en": {}}
    import json
    return json.loads(proc.stdout)


def main() -> None:
    strings = load_strings()
    zh = strings.get("zh") or {}
    if len(zh) < 40:
        fail("zh pack too small: %s" % len(zh))

    blob = []
    i18n_re = re.compile(r'data-i18n="([^"]+)"[^>]*>([^<]*)<')
    for name in PAGES:
        path = os.path.join(SITE, name)
        if not os.path.isfile(path):
            fail("missing %s" % name)
            continue
        text = open(path, encoding="utf-8").read()
        blob.append(text)
        if 'href="/' in text or 'src="/' in text:
            fail("%s uses a root-absolute asset path" % name)
        for needed in ("js/boot.js", "css/site.css", "js/i18n.js", 'lang="zh-CN"'):
            if needed not in text:
                fail("%s missing %s" % (name, needed))
        for key, inner in i18n_re.findall(text):
            if key not in zh:
                fail("%s unknown key %s" % (name, key))
            elif inner != zh[key]:
                fail("%s key %s html %r != zh %r" % (name, key, inner, zh[key]))
        if "mailto:longee142857@qq.com" not in text and name == "contact.html":
            fail("contact page missing mailto")

    gallery_js = open(os.path.join(SITE, "js", "gallery.js"), encoding="utf-8").read()
    for key in re.findall(r'\bt\("([^"]+)"\)', gallery_js):
        if key not in zh:
            fail("gallery.js missing key %s" % key)

    all_text = "\n".join(blob)
    all_text += open(os.path.join(SITE, "css", "site.css"), encoding="utf-8").read()
    all_text += open(os.path.join(SITE, "js", "i18n.js"), encoding="utf-8").read()
    all_text += gallery_js
    all_text += open(os.path.join(SITE, "README.md"), encoding="utf-8").read()
    for needle in FORBIDDEN:
        if needle in all_text:
            fail("forbidden %s" % needle)
    if re.search(r"\b\d{16,}\b", all_text):
        fail("long digit id in site")
    if "practice.longee.icu" not in all_text:
        fail("public demo host missing")
    if "token=" in all_text.lower():
        fail("token query in site")
    css = open(os.path.join(SITE, "css", "site.css"), encoding="utf-8").read()
    for color in ("#F4EDE0", "#E23B35", "#141A22", "#3A6B7C"):
        if color not in css:
            fail("css missing %s" % color)
    if not os.path.isfile(os.path.join(SITE, ".nojekyll")):
        fail("missing .nojekyll")
    readme = open(os.path.join(SITE, "README.md"), encoding="utf-8").read()
    if "/site" not in readme or "master" not in readme:
        fail("Pages instructions incomplete")
    if _fails:
        print("%s failure(s)" % _fails)
        sys.exit(1)
    print("site showcase ok (%s zh keys)" % len(zh))


if __name__ == "__main__":
    main()
