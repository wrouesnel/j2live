"""Smoke test an installed j2live: open files, render, check the output.

Run under a display, e.g.: xvfb-run python3 packaging/smoke-test.py
Pass --python PATH to render with that environment's ansible-core instead of
plain Jinja2.
"""
import os
import sys
import tempfile

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib

import j2live.app
from j2live.language_manager import LanguageManager
from j2live.mainwindow import LaunchOptions, MainWindow
from j2live.util import get_text

TEMPLATE = "{% for item in items %}\n- {{ item }}\n{% endfor %}\nenabled={{ enabled }}\n"
DATA = "items: [a, b]\nenabled: true\n"
# Plain Jinja2 drops the final newline where ansible keeps it
EXPECTED = "- a\n- b\nenabled=True"

TIMEOUT_MS = 20000


def main():
    python = sys.argv[sys.argv.index("--python") + 1] if "--python" in sys.argv else None
    workdir = tempfile.mkdtemp(prefix="j2live-smoke-")
    template_path = os.path.join(workdir, "test.txt.j2")
    data_path = os.path.join(workdir, "vars.yml")
    with open(template_path, "w") as f:
        f.write(TEMPLATE)
    with open(data_path, "w") as f:
        f.write(DATA)

    options = LaunchOptions(template=template_path, data=data_path,
                            python=python, plain=python is None)
    app = j2live.app.App(options)
    result = {"ok": False, "detail": "timed out"}

    def check(window):
        output = get_text(window.result_pane.buffer)
        if python is not None and window.environment is None:
            return True  # still probing the environment
        if window._errors:
            result["detail"] = "render errors: %s" % [e.describe() for e in window._errors]
        elif output.rstrip("\n") != EXPECTED:
            result["detail"] = "unexpected output: %r" % output
            return True
        else:
            result["ok"] = True
            result["detail"] = "rendered with %s" % (
                "ansible-core %s" % window.environment.ansible_version
                if window.environment else "plain Jinja2")
            app.close_windows()
            return False
        return True

    def started():
        windows = [w for w in app.get_windows() if isinstance(w, MainWindow)]
        if not windows:
            return True
        GLib.timeout_add(200, check, windows[0])
        return False

    def timeout():
        app.quit()
        return False

    if LanguageManager.get_language("jinja2") is None:
        print("FAIL: jinja2 syntax highlighting definition not found")
        return 1

    GLib.timeout_add(200, started)
    GLib.timeout_add(TIMEOUT_MS, timeout)
    app.run(sys.argv[:1])
    print("%s: %s" % ("PASS" if result["ok"] else "FAIL", result["detail"]))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
