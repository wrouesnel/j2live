"""Main application class"""

import argparse
import sys
from j2live import logging

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version('GtkSource', '4')

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk

import j2live.conf
import j2live.mainwindow

log = logging.getLogger()

class App(Gtk.Application):
    """j2live Gtk entrypoint"""

    def __init__(self, options: j2live.mainwindow.LaunchOptions):
        # Every launch gets its own window and process: callers such as the
        # ansible action plugin wait for the window they opened to close.
        Gtk.Application.__init__(
            self, application_id=j2live.conf.APPLICATION_ID,
            flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.options = options

    def do_activate(self):
        """Activate main application window"""
        window = j2live.mainwindow.MainWindow(self, self.options)
        window.show_all()

    def do_startup(self):
        """Main application startup window"""
        Gtk.Application.do_startup(self)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *args: self.close_windows())
        self.add_action(quit_action)

    def close_windows(self):
        """Close every window, letting each ask about unsaved changes"""
        for window in self.get_windows():
            window.close()


def parse_args(argv) -> j2live.mainwindow.LaunchOptions:
    parser = argparse.ArgumentParser(
        prog="j2live", description="Live preview for Jinja2 and Ansible templates.")
    parser.add_argument("template", nargs="?", help="template file to open")
    parser.add_argument("-d", "--data", metavar="FILE",
                        help="YAML variables file to render the template with")
    environment = parser.add_mutually_exclusive_group()
    environment.add_argument(
        "--python", metavar="PATH",
        help="Python interpreter or environment directory with ansible-core to "
             "render with (default: detect the active environment)")
    environment.add_argument("--plain", action="store_true",
                             help="render with plain Jinja2 instead of Ansible")
    parser.add_argument("--trim-blocks", action=argparse.BooleanOptionalAction,
                        default=True, help="the template module's trim_blocks (default: on)")
    parser.add_argument("--lstrip-blocks", action=argparse.BooleanOptionalAction,
                        default=False, help="the template module's lstrip_blocks (default: off)")
    parser.add_argument("--title", help="describe what is being edited in the window title")
    args = parser.parse_args(argv[1:])
    return j2live.mainwindow.LaunchOptions(
        template=args.template, data=args.data, python=args.python, plain=args.plain,
        trim_blocks=args.trim_blocks, lstrip_blocks=args.lstrip_blocks, title=args.title)


def main(argv):
    app = App(parse_args(argv))
    # Arguments are already handled; don't let GApplication try to open them
    return app.run(argv[:1])


def run():
    """Console script entrypoint"""
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
