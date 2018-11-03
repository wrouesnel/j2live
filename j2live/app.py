"""Main application class"""

import sys
from j2live import logging

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version('GtkSource', '3.0')

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk

import j2live.conf
import j2live.mainwindow

log = logging.getLogger()

class App(Gtk.Application):
    """j2live Gtk entrypoint"""

    def __init__(self):
        Gtk.Application.__init__(self)

    def do_activate(self):
        """Activate main application window"""
        window = j2live.mainwindow.MainWindow(self)
        window.show_all()

    def do_startup(self):
        """Main application startup window"""
        Gtk.Application.do_startup(self)


def main(argv):
    app = App()
    return app.run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
