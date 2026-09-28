"""A titled source editor with file loading, saving and change tracking"""
from typing import Callable, Optional

from gi.repository import Gio, GLib, GObject, Gtk, GtkSource, Pango

from j2live import logging
from j2live.conf import _
from j2live.language_manager import LanguageManager
from j2live.ui.sourcebuffer import SourceBuffer, SourceBufferState
from j2live.ui.sourcestatusbar import SourceStatusBar
from j2live.ui.sourceview import get_custom_encoding_candidates

log = logging.getLogger()

DEFAULT_TAB_WIDTH = 4
DEFAULT_SPACE_TABS = True

RESPONSE_RELOAD = 1

VISIBLE_SPACES = (GtkSource.SpaceTypeFlags.SPACE | GtkSource.SpaceTypeFlags.TAB
                  | GtkSource.SpaceTypeFlags.NEWLINE | GtkSource.SpaceTypeFlags.NBSP)

# (pane, error message or None)
DoneCallback = Callable[["EditorPane", Optional[str]], None]


class EditorPane(Gtk.Box):
    """A source view with a header naming its role and file"""

    __gtype_name__ = "EditorPane"

    __gsignals__ = {
        # The file name or modified state changed
        'file-state-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, title: str, editable: bool = True,
                 language_id: Optional[str] = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.title = title
        self.editable = editable
        self._saving = False

        self.buffer = SourceBuffer()
        if language_id:
            self.buffer.set_language(LanguageManager.get_language(language_id))

        self.view = GtkSource.View.new_with_buffer(self.buffer)
        self.view.set_show_line_numbers(True)
        self.view.set_monospace(True)
        self.view.set_highlight_current_line(True)
        self.view.set_tab_width(DEFAULT_TAB_WIDTH)
        self.view.set_insert_spaces_instead_of_tabs(DEFAULT_SPACE_TABS)
        self.view.set_editable(editable)
        self.view.props.hexpand = True
        self.view.props.vexpand = True

        scroller = Gtk.ScrolledWindow()
        scroller.add(self.view)

        self.pack_start(self._header(), False, False, 0)
        self.pack_start(self._disk_change_bar(), False, False, 0)
        self.pack_start(scroller, True, True, 0)
        self.pack_start(self._status_bar(), False, False, 0)

        self.buffer.connect("modified-changed", lambda *args: self._update_header())
        self.buffer.data.connect("file-changed", self._on_file_changed)
        self._update_header()

    def _header(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                      margin_start=8, margin_end=8, margin_top=3, margin_bottom=3)
        title = Gtk.Label(xalign=0)
        title.set_markup("<b>%s</b>" % GLib.markup_escape_text(self.title))
        box.pack_start(title, False, False, 0)

        # Separate from the file name, which is ellipsized from the start
        self.modified_label = Gtk.Label(label="•", tooltip_text=_("Unsaved changes"))
        self.modified_label.set_no_show_all(True)
        box.pack_start(self.modified_label, False, False, 0)

        self.file_label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.START)
        self.file_label.get_style_context().add_class("dim-label")
        box.pack_start(self.file_label, True, True, 0)
        return box

    def _disk_change_bar(self) -> Gtk.Widget:
        self.disk_change_bar = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING)
        self.disk_change_bar.get_content_area().add(Gtk.Label(
            label=_("The file has changed on disk."), xalign=0, wrap=True))
        self.disk_change_bar.add_button(_("_Reload"), RESPONSE_RELOAD)
        self.disk_change_bar.add_button(_("_Ignore"), Gtk.ResponseType.CLOSE)
        self.disk_change_bar.connect("response", self._on_disk_change_response)
        self.disk_change_bar.set_revealed(False)
        return self.disk_change_bar

    def _status_bar(self) -> Gtk.Widget:
        status_bar = SourceStatusBar()
        status_bar.props.visible = True

        def bind_adapt_cursor_position(binding, from_value):
            buf = binding.get_source()
            cursor_it = buf.get_iter_at_offset(from_value)
            return (cursor_it.get_line(), cursor_it.get_line_offset())

        # Set cursor position to 0,0 initially...
        status_bar.props.cursor_position = (0,0)

        # Setup the status bar properly (also copied from meld)
        self.buffer.bind_property("cursor-position", status_bar, "cursor_position",
                                  GObject.BindingFlags.DEFAULT,
                                  bind_adapt_cursor_position)

        self.buffer.bind_property(
            'language', status_bar, 'source-language',
            GObject.BindingFlags.BIDIRECTIONAL)

        self.buffer.data.bind_property(
            'encoding', status_bar, 'source-encoding',
            GObject.BindingFlags.DEFAULT)

        # TODO: reload with a user-chosen encoding
        status_bar.connect(
            'go-to-line', lambda widget, line: self.go_to_line(line, focus=False))
        return status_bar

    @property
    def gfile(self) -> Optional[Gio.File]:
        return self.buffer.data.gfile

    @property
    def path(self) -> Optional[str]:
        return self.gfile.get_path() if self.gfile is not None else None

    @property
    def display_name(self) -> str:
        return self.gfile.get_basename() if self.gfile is not None else _("Untitled")

    @property
    def modified(self) -> bool:
        """Has unsaved edits worth warning about"""
        return self.editable and self.buffer.get_modified()

    def _update_header(self):
        if self.gfile is not None:
            text = self.gfile.get_parse_name()
        elif self.editable:
            text = _("unsaved")
        else:
            text = ""
        self.modified_label.set_visible(self.modified)
        self.file_label.set_text(text)
        self.file_label.set_tooltip_text(text or None)
        self.emit("file-state-changed")

    def set_show_whitespace(self, show: bool):
        drawer = self.view.get_space_drawer()
        drawer.set_types_for_locations(
            GtkSource.SpaceLocationFlags.ALL,
            VISIBLE_SPACES if show else GtkSource.SpaceTypeFlags.NONE)
        drawer.set_enable_matrix(show)

    def go_to_line(self, line: int, focus: bool = True):
        self.buffer.place_cursor(self.buffer.get_iter_at_line(line))
        self.view.scroll_to_mark(self.buffer.get_insert(), 0.1, False, 0, 0)
        if focus:
            self.view.grab_focus()

    def load(self, gfile: Gio.File, on_done: Optional[DoneCallback] = None,
             language=None):
        """Load a file, replacing the buffer contents"""
        if language is not None:
            self.buffer.set_language(language)

        line = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_line()
        reloading = self.gfile is not None and gfile.equal(self.gfile)

        self.buffer.data.reset(gfile=gfile, state=SourceBufferState.LOADING)
        self.disk_change_bar.set_revealed(False)
        loader = GtkSource.FileLoader.new(self.buffer, self.buffer.data.sourcefile)
        loader.set_candidate_encodings(get_custom_encoding_candidates())

        def loaded(loader, result, data):
            error = None
            try:
                loader.load_finish(result)
                self.buffer.data.state = SourceBufferState.LOAD_FINISHED
            except GLib.Error as err:
                if err.matches(GLib.convert_error_quark(),
                               GLib.ConvertError.ILLEGAL_SEQUENCE):
                    # GtkSourceView's loader doesn't finish its in-progress
                    # user-action on this error (bgo#795387); tidy up so the
                    # buffer isn't left in a corrupt state.
                    self.buffer.end_not_undoable_action()
                    self.buffer.end_user_action()
                self.buffer.data.state = SourceBufferState.LOAD_ERROR
                error = err.message
                log.error("Could not load file", file=gfile.get_parse_name(), error=error)
            else:
                self.buffer.set_modified(False)
                if reloading:
                    self.buffer.place_cursor(self.buffer.get_iter_at_line(line))
                else:
                    self.buffer.place_cursor(self.buffer.get_start_iter())
            self._update_header()
            if on_done:
                on_done(self, error)

        loader.load_async(GLib.PRIORITY_DEFAULT, None, None, None, loaded, None)

    def save(self, parent: Gtk.Window, on_done: Optional[DoneCallback] = None):
        """Save to the current file, asking for one if there isn't one yet"""
        if self.gfile is None:
            self.save_as(parent, on_done)
        else:
            self._save_to(self.gfile, on_done)

    def save_as(self, parent: Gtk.Window, on_done: Optional[DoneCallback] = None):
        dialog = Gtk.FileChooserNative.new(
            _("Save %s") % self.title, parent, Gtk.FileChooserAction.SAVE, None, None)
        dialog.set_do_overwrite_confirmation(True)
        if self.gfile is not None:
            dialog.set_file(self.gfile)
        response = dialog.run()
        gfile = dialog.get_file()
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT or gfile is None:
            if on_done:
                on_done(self, _("Cancelled"))
            return
        self._save_to(gfile, on_done)

    def _save_to(self, gfile: Gio.File, on_done: Optional[DoneCallback]):
        same_file = self.gfile is not None and gfile.equal(self.gfile)
        saver = GtkSource.FileSaver.new_with_target(
            self.buffer, self.buffer.data.sourcefile, gfile)
        # Changes on disk are already surfaced by the disk change bar, so
        # saving is an explicit choice to overwrite them.
        saver.set_flags(GtkSource.FileSaverFlags.IGNORE_MODIFICATION_TIME)
        self._saving = True

        def saved(saver, result, data):
            self._saving = False
            error = None
            try:
                saver.save_finish(result)
            except GLib.Error as err:
                error = err.message
                log.error("Could not save file", file=gfile.get_parse_name(), error=error)
            else:
                self.buffer.set_modified(False)
                if same_file:
                    self.buffer.data.update_mtime()
                else:
                    self.buffer.data.reset(gfile=gfile, state=SourceBufferState.LOAD_FINISHED)
                self.disk_change_bar.set_revealed(False)
            self._update_header()
            if on_done:
                on_done(self, error)

        saver.save_async(GLib.PRIORITY_DEFAULT, None, None, None, saved, None)

    def _on_file_changed(self, data):
        if self._saving:
            return
        if self.modified:
            # Don't throw away edits; let the user decide
            self.disk_change_bar.set_revealed(True)
        else:
            self.load(self.gfile)

    def _on_disk_change_response(self, bar, response_id):
        bar.set_revealed(False)
        if response_id == RESPONSE_RELOAD:
            self.load(self.gfile)
        else:
            # Treat the version on disk as seen
            self.buffer.data.update_mtime()
