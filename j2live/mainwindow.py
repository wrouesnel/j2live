"""Main window routines"""

from j2live import logging

from gi.repository import Gtk
from gi.repository import GtkSource

from j2live.conf import _

import ruamel.yaml as yaml
import jinja2

from j2live.util import template_from_string, get_text

log = logging.getLogger()


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        Gtk.Window.__init__(self, title=_("j2live"), application=app)
        self.set_size_request(800, 500)

        # Initialize panes
        mainpane: Gtk.Paned
        mainpane = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        # Set initial size to 50/50
        mainpane.set_position(self.get_size()[0] / 2)

        # Build the editor pane
        editorpane: Gtk.Paned
        editorpane = Gtk.Paned.new(Gtk.Orientation.VERTICAL)
        editorpane.set_position((self.get_size()[1] / 3) * 2)

        # Editor window
        self.editor: GtkSource.View
        self.editor = GtkSource.View.new()
        self.editor.set_show_line_numbers(True)
        self.editor.set_monospace(True)

        # Data editor window
        self.dataeditor: GtkSource.View
        self.dataeditor = GtkSource.View.new()
        self.dataeditor.set_show_line_numbers(True)
        self.dataeditor.set_monospace(True)

        editorpane.add1(self.editor)
        editorpane.add2(self.dataeditor)

        # Result viewer stands alone
        self.resultview: GtkSource.View
        self.resultview = GtkSource.View.new()
        self.resultview.set_show_line_numbers(True)
        self.resultview.set_editable(False)
        self.resultview.set_monospace(True)

        mainpane.add1(editorpane)
        mainpane.add2(self.resultview)

        self.add(mainpane)

        # Hook up signals for the main editor
        self.dataeditor.get_buffer().connect("changed", self.data_updated, None)
        self.editor.get_buffer().connect("changed", self.data_updated, None)

        # Initialize local data
        self.data = {}
        self.template = template_from_string(get_text(self.dataeditor.get_buffer()))

        # Grab the default input editor
        self.editor.grab_focus()

    def data_updated(self, buffer: Gtk.TextBuffer, data):
        """Notify the application that source data has been updated.

        Should be called everytime dependent data for the render
        is updated. It does not necessarily re-render immediately though in order
        to deduplicate the events.
        """
        log.debug("Text buffer updated")

        # TODO: notify when the render fails and with whom it fails!
        if buffer is self.dataeditor.get_buffer():
            try:
                new_data = yaml.safe_load(get_text(buffer))
            except Exception as e:
                log.exception("Could not parse data input", exc_info=e)
                return
            self.data = new_data
            log.debug("Data replaced")
        elif buffer is self.editor.get_buffer():
            try:
                rtemplate = template_from_string(get_text(buffer))
            except Exception as e:
                log.exception("Could not parse input template", exc_info=e)
                return
            self.template = rtemplate
            log.debug("Template replaced")

        # Re-render based on the new template or data or both
        try:
            new_result = self.template.render(**self.data)
        except Exception as e:
            log.exception("Could not render the template", exc_info=e)
            return

        self.resultview.get_buffer().set_text(new_result)
        log.debug("Re-Rendered results")
