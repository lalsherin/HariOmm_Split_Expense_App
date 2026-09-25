"""Test-only copy of the phone build with one hook into the app's closure.

The page the APK carries (android/assets/index.html) wraps everything in an
IIFE, so a test cannot otherwise call its functions. This adds
`window.__t(code)` just before the closure ends and writes the result to
e2e/www/. It is never shipped.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
src_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "android" / "assets" / "index.html"
out_name = sys.argv[2] if len(sys.argv) > 2 else "index.html"
src = src_path.read_text(encoding="utf-8")
i = src.rindex("})();")
out = src[:i] + "window.__t = function (code) { return eval(code); };\n" + src[i:]
(HERE / "www").mkdir(exist_ok=True)
(HERE / "www" / out_name).write_text(out, encoding="utf-8")
print("wrote", HERE / "www" / out_name)
