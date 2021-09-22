"""Main window routines"""

from j2live import logging

from gi.repository import Gtk
from gi.repository import GtkSource

from j2live.conf import _

import ruamel.yaml as yaml

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from j2live.util import get_text

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

        # Scrolled windows
        editor_window = Gtk.ScrolledWindow()
        editor_window.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC)
        
        dataeditor_window = Gtk.ScrolledWindow()
        dataeditor_window.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC)
        
        resultview_window = Gtk.ScrolledWindow()
        resultview_window.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC)

        editorpane.add1(editor_window)
        editorpane.add2(dataeditor_window)
        
        editorpane.add1(editor_window)
        editorpane.add2(dataeditor_window)
        
        mainpane.add1(editorpane)
        mainpane.add2(resultview_window)

        # Editor window
        self.editor: GtkSource.View
        self.editor = GtkSource.View.new()
        self.editor.set_show_line_numbers(True)
        self.editor.set_monospace(True)
        
        editor_window.add(self.editor)

        # Data editor window
        self.dataeditor: GtkSource.View
        self.dataeditor = GtkSource.View.new()
        self.dataeditor.set_show_line_numbers(True)
        self.dataeditor.set_monospace(True)

        dataeditor_window.add(self.dataeditor)

        # Result viewer stands alone
        self.resultview: GtkSource.View
        self.resultview = GtkSource.View.new()
        self.resultview.set_show_line_numbers(True)
        self.resultview.set_editable(False)
        self.resultview.set_monospace(True)

        resultview_window.add(self.resultview)

        # Add the children...
        self.add(mainpane)

        # Hook up signals for the main editor
        self.dataeditor.get_buffer().connect("changed", self.data_updated, None)
        self.editor.get_buffer().connect("changed", self.data_updated, None)

        # Initialize local data
        self.loader = DataLoader()
        self.templar = Templar(None, variables={})

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
            try:
                self.templar.set_available_variables(new_data)
            except Exception as e:
                log.exception("Could not set data input", exc_info=e)
            log.debug("Data replaced")
        # Re-render based on the new template or data or both
        try:
            new_result = self.templar.template(get_text(self.editor.get_buffer()))
        except Exception as e:
            log.exception("Could not render the template", exc_info=e)
            return

        self.resultview.get_buffer().set_text(str(new_result))
        log.debug("Re-Rendered results")
