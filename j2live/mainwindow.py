"""Main window routines"""
import functools
from typing import Tuple

from j2live import logging, ui
from j2live.language_manager import LanguageManager
from j2live.ui.sourcebuffer import SourceBuffer, SourceBufferState
from j2live.ui.sourcestatusbar import SourceStatusBar

from gi.repository import Gtk, GLib, GObject
from gi.repository import GtkSource

from j2live.conf import _

import ruamel.yaml
import jinja2

from j2live.ui.sourceview import get_custom_encoding_candidates

yaml = ruamel.yaml.YAML(typ='rt')

from j2live.util import template_from_string, get_text

log = logging.getLogger()

DEFAULT_TAB_WIDTH = 4
DEFAULT_SPACE_TABS = True

class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        Gtk.Window.__init__(self, title=_("j2live"), application=app)
        self.set_size_request(800, 500)

        # self.template_file = None
        # self.data_file = None

        # grid = Gtk.Grid()
        # self.add(grid)

        # Menu bar
        menubar = self._menubar()

        box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL,spacing=0)
        self.add(box)

        box.add(menubar)
        box.pack_start(menubar, False, False,0)

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
        template_editor, self.template_buffer = self._source_editor()
        data_editor, self.data_buffer = self._source_editor()

        # Result viewer stands alone
        result_editor, self.result_buffer = self._source_editor(editable=False)

        editorpane.add1(template_editor)
        editorpane.add2(data_editor)

        mainpane.add1(editorpane)
        mainpane.add2(result_editor)

        # Add configure main pane
        mainpane.set_vexpand(True)
        mainpane.set_hexpand(True)

        # Add to the box
        box.add(mainpane)

        # Main initialization logic

        # Hook up signals for the main editor
        self.data_buffer.connect("changed", self.data_updated, None)
        self.template_buffer.connect("changed", self.data_updated, None)

        # Initialize local data
        self.data = {}
        self.template = template_from_string(get_text(self.data_buffer))

        # Grab the default input editor
        template_editor.grab_focus()

    def _menubar(self) -> Gtk.MenuBar:
        menubar : Gtk.MenuBar
        menubar = Gtk.MenuBar.new()
        menubar.set_hexpand(True)

        menu_file = self._add_submenu(menubar, 'File')
        menu_file_open_template = self._add_menuitem(menu_file, 'Open Template')
        menu_file_open_template.connect('activate', self.on_menu_open_template)
        menu_file_open_data = self._add_menuitem(menu_file, 'Open Data')
        menu_file_open_data.connect('activate', self.on_menu_open_data)
        self._add_menuspacer(menu_file)
        # menu_file_save = self._add_menuitem(menu_file, 'Save')
        # menu_file_save.connect('activate', self.on_menu_save)
        # self._add_menuspacer(menu_file)
        menu_quit = self._add_menuitem(menu_file, 'Quit')
        menu_quit.connect('activate', self.on_menu_quit)

        menu_edit = self._add_submenu(menubar, 'Edit')
        menu_edit_cut = self._add_menuitem(menu_edit, 'Cut')
        menu_edit_cut.connect('activate', functools.partial(self._signal_for_current_widget,"cut-clipboard"))
        menu_edit_copy = self._add_menuitem(menu_edit, 'Copy')
        menu_edit_copy.connect('activate', functools.partial(self._signal_for_current_widget,"copy-clipboard"))
        menu_edit_paste = self._add_menuitem(menu_edit, 'Paste')
        menu_edit_paste.connect('activate', functools.partial(self._signal_for_current_widget,"paste-clipboard"))

        menu_help = self._add_submenu(menubar, 'Help')
        menu_help_about = self._add_menuitem(menu_help, "About")
        menu_help_about.connect("activate", self.on_menu_about)

        return menubar

    def _add_submenu(self, menubar, label) -> Gtk.Menu:
        menuitem = Gtk.MenuItem(label=label)

        submenu = Gtk.Menu()
        menuitem.set_submenu(submenu)

        menubar.add(menuitem)
        return submenu

    def _add_menuitem(self, submenu, label):
        menuitem = Gtk.MenuItem(label=label)
        submenu.add(menuitem)
        return menuitem

    def _add_menuspacer(self, submenu):
        menuitem = Gtk.SeparatorMenuItem()
        submenu.add(menuitem)
        return menuitem

    def _source_editor(self, editable=True) -> Tuple[Gtk.Widget, GtkSource.Buffer]:
        """_source_editor builds a complete source editor object"""

        box: Gtk.Box
        box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL,spacing=0)

        container: Gtk.ScrolledWindow
        container = Gtk.ScrolledWindow()

        buffer: SourceBuffer
        buffer = SourceBuffer()

        editor: GtkSource.View
        editor = GtkSource.View.new_with_buffer(buffer)
        editor.set_show_line_numbers(True)
        editor.set_monospace(True)
        editor.set_highlight_current_line(True)
        editor.set_tab_width(DEFAULT_TAB_WIDTH)
        editor.set_insert_spaces_instead_of_tabs(DEFAULT_SPACE_TABS)
        # TODO: just let the props be exposed?
        editor.props.editable = True

        editor.props.hexpand = True
        editor.props.vexpand = True

        container.add(editor)

        status_bar = SourceStatusBar()
        status_bar.props.visible = True

        def bind_adapt_cursor_position(binding, from_value):
            buf = binding.get_source()
            cursor_it = buf.get_iter_at_offset(from_value)
            # offset = textview.get_visual_column(cursor_it)
            line = cursor_it.get_line()
            return (line, from_value)

        # Set cursor position to 0,0 initially...
        status_bar.props.cursor_position = (0,0)

        # Setup the status bar properly (also copied from meld)
        buffer.bind_property("cursor-position", status_bar, "cursor_position",
                             GObject.BindingFlags.DEFAULT,
                             bind_adapt_cursor_position,
                             )

        buffer.bind_property(
            'language', status_bar, 'source-language',
            GObject.BindingFlags.BIDIRECTIONAL)

        buffer.data.bind_property(
            'encoding', status_bar, 'source-encoding',
            GObject.BindingFlags.DEFAULT)

        # def reload_with_encoding(widget, encoding, pane):
        #     if not self.check_unsaved_changes([buffer]):
        #         return
        #     self.set_file(pane, buffer.data.gfile, encoding)

        def go_to_line(widget, line, pane):
            if self.cursor.pane == pane and self.cursor.line == line:
                return
            self.move_cursor(pane, line, focus=False)

        # TODO:
        # status_bar.connect('encoding-changed', reload_with_encoding, editor)
        status_bar.connect('go-to-line', go_to_line, editor)

        box.add(container)
        box.add(status_bar)

        return box, buffer

    def _signal_for_current_widget(self, signal_name, *args):
        """_signal_for_current_widget emits the named signal against the currently focused widget"""
        widget = self.get_focus()
        widget.emit(signal_name)

    def on_menu_open_template(self, widget):
        dialog = Gtk.FileChooserDialog("Select template", self,
                                       Gtk.FileChooserAction.OPEN,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                        Gtk.STOCK_OK, Gtk.ResponseType.OK))
        dialog.run()
        file = dialog.get_file()

        source_file = GtkSource.File.new()
        source_file.set_location(file)

        lang = LanguageManager.get_language_from_file(file)
        self.template_buffer.set_language(lang)
        # If we guess a non-template language, then it's probably what we're expecting in the output pane.
        self.result_buffer.set_language(lang)

        loader: GtkSource.FileLoader
        loader = GtkSource.FileLoader.new(self.template_buffer, source_file)
        loader.set_candidate_encodings(get_custom_encoding_candidates())
        loader.load_async(GLib.PRIORITY_DEFAULT, None, None,
                          None, self.file_loaded, self.template_buffer)


        dialog.destroy()

    def on_menu_open_data(self, widget):
        dialog = Gtk.FileChooserDialog("Select data", self,
                                       Gtk.FileChooserAction.OPEN,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                        Gtk.STOCK_OK, Gtk.ResponseType.OK))
        dialog.run()
        file = dialog.get_file()

        source_file = GtkSource.File.new()
        source_file.set_location(file)

        self.data_buffer.set_language(LanguageManager.get_language_from_file(file))

        loader: GtkSource.FileLoader
        loader = GtkSource.FileLoader.new(self.data_buffer, source_file)
        loader.set_candidate_encodings(get_custom_encoding_candidates())
        loader.load_async(GLib.PRIORITY_DEFAULT, None, None,
                          None, self.file_loaded, self.data_buffer)

        dialog.destroy()

    def file_loaded(self, loader, result, user_data):
        buf : SourceBuffer
        buf = user_data
        try:
            loader.load_finish(result)
            buf.data.state = SourceBufferState.LOAD_FINISHED
        except GLib.Error as err:
            if err.matches(
                    GLib.convert_error_quark(),
                    GLib.ConvertError.ILLEGAL_SEQUENCE):
                # While there are probably others, this is the main
                # case where GtkSourceView's loader doesn't finish its
                # in-progress user-action on error. See bgo#795387 for
                # the GtkSourceView bug report.
                #
                # The handling here is fragile, but it's better than
                # getting into a non-obvious corrupt state.
                buf.end_not_undoable_action()
                buf.end_user_action()
            if err.domain == GLib.quark_to_string(
                    GtkSource.FileLoaderError.quark()):
                # TODO: Add custom reload-with-encoding handling for
                # GtkSource.FileLoaderError.CONVERSION_FALLBACK and
                # GtkSource.FileLoaderError.ENCODING_AUTO_DETECTION_FAILED
                pass
            buf.data.state = SourceBufferState.LOAD_ERROR

    def on_menu_save(self, widget):
        # TODO: save things
        pass

    def on_menu_quit(self, widget):
        Gtk.main_quit()

    def on_menu_about(self, widget):
        Gtk.main_quit()
        about_dialog = Gtk.AboutDialog(
            program_name="j2live",
            title="About j2live",
        )
        about_dialog.run()
        about_dialog.destroy()

    def data_updated(self, buffer: Gtk.TextBuffer, data):
        """Notify the application that source data has been updated.

        Should be called everytime dependent data for the render
        is updated. It does not necessarily re-render immediately though in order
        to deduplicate the events.
        """
        log.debug("Text buffer updated")

        # TODO: notify when the render fails and with whom it fails!
        if buffer is self.data_buffer:
            try:
                new_data = yaml.load(get_text(buffer))
            except Exception as e:
                log.exception("Could not parse data input", exc_info=e)
                return
            self.data = new_data
            log.debug("Data replaced")
        elif buffer is self.template_buffer:
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

        self.result_buffer.set_text(new_result)
        log.debug("Re-Rendered results")
