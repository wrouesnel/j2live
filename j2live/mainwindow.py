"""Main window routines"""
import functools
from importlib import metadata
from typing import Optional, Tuple

from j2live import logging
from j2live.language_manager import LanguageManager
from j2live.environments import (
    AnsibleWorker, PythonEnvironment, detect_interpreters, interpreter_for_prefix, probe)
from j2live.render import ErrorSource, RenderError, RenderResult, render_plain
from j2live.ui.sourcebuffer import SourceBuffer, SourceBufferState
from j2live.ui.sourcestatusbar import SourceStatusBar

from gi.repository import Gdk, Gio, Gtk, GLib, GObject, Pango
from gi.repository import GtkSource

from j2live.conf import _

from j2live.ui.sourceview import get_custom_encoding_candidates

from j2live.util import get_text

log = logging.getLogger()

DEFAULT_TAB_WIDTH = 4
DEFAULT_SPACE_TABS = True

DEFAULT_WIDTH = 1100
DEFAULT_HEIGHT = 700

# Delay after the last edit before re-rendering, so errors don't flicker
# while a tag is half typed.
RENDER_DELAY_MS = 150

# Renders faster than this don't flash a spinner
SPINNER_DELAY_MS = 250

ERROR_MARK_CATEGORY = "j2live-error"
RESPONSE_GO_TO_ERROR = 1


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        Gtk.Window.__init__(self, title=_("j2live"), application=app)
        self.set_size_request(800, 500)
        self.set_default_size(DEFAULT_WIDTH, DEFAULT_HEIGHT)

        # Ansible environment used for rendering; None renders with plain Jinja2
        self.environments: list[PythonEnvironment] = []
        self.environment: Optional[PythonEnvironment] = None
        self.worker: Optional[AnsibleWorker] = None

        # Menu bar
        menubar = self._menubar()

        box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL,spacing=0)
        self.add(box)

        box.pack_start(menubar, False, False,0)
        box.pack_start(self._environment_bar(), False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 0)

        # Initialize panes
        mainpane: Gtk.Paned
        mainpane = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        # Set initial size to 50/50
        mainpane.set_position(DEFAULT_WIDTH // 2)

        # Build the editor pane
        editorpane: Gtk.Paned
        editorpane = Gtk.Paned.new(Gtk.Orientation.VERTICAL)
        editorpane.set_position((DEFAULT_HEIGHT // 3) * 2)

        # Editor window
        template_editor, self.template_buffer, self.template_view = self._source_editor()
        data_editor, self.data_buffer, self.data_view = self._source_editor()

        # Result viewer stands alone
        result_editor, self.result_buffer, self.result_view = self._source_editor(editable=False)

        editorpane.add1(template_editor)
        editorpane.add2(data_editor)

        mainpane.add1(editorpane)
        mainpane.add2(self._result_pane(result_editor))

        # Add configure main pane
        mainpane.set_vexpand(True)
        mainpane.set_hexpand(True)

        # Add to the box
        box.add(mainpane)

        # Main initialization logic

        # Hook up signals for the main editor
        self.data_buffer.connect("changed", self.data_updated)
        self.template_buffer.connect("changed", self.data_updated)

        self._render_source_id = None
        self._errors: list[RenderError] = []
        self._detect_environments()
        self.connect("destroy", lambda *args: self.worker and self.worker.stop())

        # Focus can only be grabbed once the window is mapped
        self.connect("map", lambda *args: self.template_view.grab_focus())

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

    def _environment_bar(self) -> Gtk.Widget:
        """Shows which Python environment renders templates, and switches it"""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                      margin_start=6, margin_end=6, margin_top=2, margin_bottom=2)

        self.environment_label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.START)
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.pack_start(
            Gtk.Image.new_from_icon_name("utilities-terminal-symbolic", Gtk.IconSize.MENU),
            False, False, 0)
        button_box.pack_start(self.environment_label, True, True, 0)
        button_box.pack_start(
            Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU),
            False, False, 0)

        self.environment_button = Gtk.MenuButton(relief=Gtk.ReliefStyle.NONE)
        self.environment_button.add(button_box)
        self.environment_button.set_popover(self._environment_popover())
        bar.pack_start(self.environment_button, False, False, 0)

        self.render_spinner = Gtk.Spinner(tooltip_text=_("Rendering…"))
        self.render_spinner.set_no_show_all(True)
        bar.pack_start(self.render_spinner, False, False, 0)
        self._spinner_source_id = None

        self._update_environment_label()
        return bar

    def _environment_popover(self) -> Gtk.Popover:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=6)

        heading = Gtk.Label(xalign=0)
        heading.set_markup("<b>%s</b>" % _("Render templates with"))
        box.pack_start(heading, False, False, 0)

        self.environment_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.environment_list.get_style_context().add_class("frame")
        self.environment_list.connect("row-activated", self.on_environment_row_activated)
        box.pack_start(self.environment_list, False, False, 0)

        choose = Gtk.Button(label=_("Choose Environment Folder…"))
        choose.connect("clicked", self.on_choose_environment)
        box.pack_start(choose, False, False, 0)

        box.show_all()
        popover = Gtk.Popover()
        popover.add(box)
        return popover

    def _environment_row(self, env: Optional[PythonEnvironment]) -> Gtk.ListBoxRow:
        if env is None:
            title = _("Plain Jinja2")
            detail = _("No Ansible: stock Jinja2 settings and filters")
        else:
            title = env.display_prefix
            if env.has_ansible:
                detail = _("ansible-core %s · Python %s") % (
                    env.ansible_version, env.python_version)
            elif env.error or env.python_version:
                detail = _("ansible-core not available")
            else:
                detail = _("Checking…")

        grid = Gtk.Grid(column_spacing=8, margin=6)
        check = Gtk.Image.new_from_icon_name("object-select-symbolic", Gtk.IconSize.MENU)
        check.set_opacity(1.0 if env is self.environment else 0.0)
        grid.attach(check, 0, 0, 1, 2)
        grid.attach(Gtk.Label(label=title, xalign=0), 1, 0, 1, 1)
        detail_label = Gtk.Label(xalign=0)
        detail_label.set_markup("<small>%s</small>" % GLib.markup_escape_text(detail))
        detail_label.get_style_context().add_class("dim-label")
        grid.attach(detail_label, 1, 1, 1, 1)

        row = Gtk.ListBoxRow()
        row.add(grid)
        row.environment = env
        row.set_sensitive(env is None or env.has_ansible)
        if env is not None:
            row.set_tooltip_text(env.error or env.python)
        row.show_all()
        return row

    def _refresh_environments(self):
        for row in self.environment_list.get_children():
            self.environment_list.remove(row)
        for env in self.environments:
            self.environment_list.add(self._environment_row(env))
        self.environment_list.add(self._environment_row(None))
        self._update_environment_label()

    def _update_environment_label(self):
        env = self.environment
        if env is not None:
            markup = "%s  <span alpha='60%%'>ansible-core %s</span>" % (
                GLib.markup_escape_text(env.display_prefix),
                GLib.markup_escape_text(env.ansible_version))
            tooltip = _("Rendering with ansible-core %s from %s (Python %s)") % (
                env.ansible_version, env.python, env.python_version)
        elif any(not (e.has_ansible or e.error or e.python_version) for e in self.environments):
            markup = _("Looking for Ansible…")
            tooltip = None
        else:
            markup = "%s  <span alpha='60%%'>%s</span>" % (
                _("Plain Jinja2"), _("no Ansible environment selected"))
            tooltip = _("Click to choose a Python environment with ansible-core")
        self.environment_label.set_markup(markup)
        self.environment_button.set_tooltip_text(tooltip)

    def _detect_environments(self):
        """Probe likely environments and use the first with ansible-core"""
        self.environments = [PythonEnvironment(python) for python in detect_interpreters()]
        self._refresh_environments()

        def probed(env):
            self._refresh_environments()
            pending = [e for e in self.environments
                       if not (e.has_ansible or e.error or e.python_version)]
            if pending or self.environment is not None:
                return
            found = next((e for e in self.environments if e.has_ansible), None)
            log.info("Detected environments",
                     environments=[(e.python, e.ansible_version) for e in self.environments])
            if found is not None:
                self._select_environment(found)

        for env in self.environments:
            probe(env, probed)

    def _select_environment(self, env: Optional[PythonEnvironment]):
        if self.worker is not None:
            self.worker.stop()
            self._set_rendering(False)
        self.environment = env
        self.worker = AnsibleWorker(env) if env is not None else None
        self._refresh_environments()
        self._rerender()

    def on_environment_row_activated(self, listbox, row):
        self.environment_button.get_popover().popdown()
        if row.environment is not self.environment:
            self._select_environment(row.environment)

    def on_choose_environment(self, button):
        self.environment_button.get_popover().popdown()
        dialog = Gtk.FileChooserDialog(
            title=_("Choose Python Environment"), transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons(
            _("_Cancel"), Gtk.ResponseType.CANCEL,
            _("_Select"), Gtk.ResponseType.OK)
        try:
            if dialog.run() != Gtk.ResponseType.OK:
                return
            prefix = dialog.get_filename()
        finally:
            dialog.destroy()
        self.use_environment_folder(prefix)

    def use_environment_folder(self, prefix: str):
        """Switch to the Python environment in prefix, if it has ansible-core"""
        python = interpreter_for_prefix(prefix)
        if python is None:
            self._show_message(
                Gtk.MessageType.ERROR, _("No Python interpreter found"),
                _("%s does not look like a Python environment.") % prefix)
            return

        env = next((e for e in self.environments if e.python == python), None)
        if env is None:
            env = PythonEnvironment(python)
            self.environments.append(env)

        def probed(env):
            self._refresh_environments()
            if env.has_ansible:
                self._select_environment(env)
            else:
                self._show_message(
                    Gtk.MessageType.ERROR, _("ansible-core is not available"),
                    _("Could not import ansible from %s:\n%s") % (env.python, env.error))

        probe(env, probed)

    def _result_pane(self, result_editor: Gtk.Widget) -> Gtk.Widget:
        """Wrap the result editor with a bar for reporting render errors"""
        box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.error_bar = Gtk.InfoBar(message_type=Gtk.MessageType.ERROR)
        self.error_label = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.error_bar.get_content_area().add(self.error_label)
        self.error_goto_button = self.error_bar.add_button(
            _("Go to Error"), RESPONSE_GO_TO_ERROR)
        self.error_bar.connect("response", self.on_error_bar_response)
        self.error_bar.set_revealed(False)

        box.pack_start(self.error_bar, False, False, 0)
        box.pack_start(result_editor, True, True, 0)
        return box

    def _source_editor(self, editable=True) -> Tuple[Gtk.Widget, SourceBuffer, GtkSource.View]:
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
        editor.props.editable = editable

        editor.props.hexpand = True
        editor.props.vexpand = True

        if editable:
            self._setup_error_marks(editor)

        container.add(editor)

        status_bar = SourceStatusBar()
        status_bar.props.visible = True

        def bind_adapt_cursor_position(binding, from_value):
            buf = binding.get_source()
            cursor_it = buf.get_iter_at_offset(from_value)
            return (cursor_it.get_line(), cursor_it.get_line_offset())

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

        # TODO: reload with a user-chosen encoding
        # status_bar.connect('encoding-changed', reload_with_encoding, editor)
        status_bar.connect(
            'go-to-line', lambda widget, line: self.go_to_line(editor, line, focus=False))

        box.add(container)
        box.add(status_bar)

        return box, buffer, editor

    def _setup_error_marks(self, view: GtkSource.View):
        """Highlight lines carrying an error mark, with the message as a tooltip"""
        background = Gdk.RGBA()
        background.parse("rgba(224, 27, 36, 0.2)")

        attrs = GtkSource.MarkAttributes()
        attrs.set_icon_name("dialog-error-symbolic")
        attrs.set_background(background)
        attrs.connect("query-tooltip-text", self._error_mark_tooltip)
        attrs.connect("query-tooltip-markup", lambda attrs, mark: None)

        view.set_mark_attributes(ERROR_MARK_CATEGORY, attrs, 0)
        view.set_show_line_marks(True)

    def _error_mark_tooltip(self, attrs, mark) -> str:
        buffer = mark.get_buffer()
        line = buffer.get_iter_at_mark(mark).get_line()
        return "\n".join(
            e.describe() for e in self._errors
            if self._view_for_error(e).get_buffer() is buffer and e.line == line)

    def _view_for_error(self, error: RenderError) -> GtkSource.View:
        if error.source is ErrorSource.DATA:
            return self.data_view
        return self.template_view

    def go_to_line(self, view: GtkSource.View, line: int, focus: bool = True):
        buffer = view.get_buffer()
        buffer.place_cursor(buffer.get_iter_at_line(line))
        view.scroll_to_mark(buffer.get_insert(), 0.1, False, 0, 0)
        if focus:
            view.grab_focus()

    def _signal_for_current_widget(self, signal_name, *args):
        """_signal_for_current_widget emits the named signal against the currently focused widget"""
        widget = self.get_focus()
        if widget is None or not GObject.signal_lookup(signal_name, type(widget)):
            return
        widget.emit(signal_name)

    def _choose_file(self, title: str) -> Optional[Gio.File]:
        dialog = Gtk.FileChooserDialog(
            title=title, transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(
            _("_Cancel"), Gtk.ResponseType.CANCEL,
            _("_Open"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        try:
            if dialog.run() != Gtk.ResponseType.OK:
                return None
            return dialog.get_file()
        finally:
            dialog.destroy()

    def _load_file(self, buffer: SourceBuffer, file):
        buffer.data.reset(gfile=file, state=SourceBufferState.LOADING)

        loader: GtkSource.FileLoader
        loader = GtkSource.FileLoader.new(buffer, buffer.data.sourcefile)
        loader.set_candidate_encodings(get_custom_encoding_candidates())
        loader.load_async(GLib.PRIORITY_DEFAULT, None, None,
                          None, self.file_loaded, buffer)

    def on_menu_open_template(self, widget):
        file = self._choose_file(_("Open Template"))
        if file is None:
            return

        lang = LanguageManager.get_language_from_file(file)
        self.template_buffer.set_language(lang)
        # If we guess a non-template language, then it's probably what we're expecting in the output pane.
        self.result_buffer.set_language(lang)

        self._load_file(self.template_buffer, file)

    def on_menu_open_data(self, widget):
        file = self._choose_file(_("Open Data"))
        if file is None:
            return

        self.data_buffer.set_language(LanguageManager.get_language_from_file(file))

        self._load_file(self.data_buffer, file)

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
            log.error("Could not load file", file=buf.data.label, error=err.message)
            self._show_message(
                Gtk.MessageType.ERROR,
                _("Could not open %s") % buf.data.label,
                err.message)

    def _show_message(self, message_type: Gtk.MessageType, text: str, secondary: str):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=message_type,
            buttons=Gtk.ButtonsType.CLOSE, text=text, secondary_text=secondary)
        dialog.run()
        dialog.destroy()

    def on_menu_save(self, widget):
        # TODO: save things
        pass

    def on_menu_quit(self, widget):
        self.get_application().quit()

    def on_menu_about(self, widget):
        try:
            version = metadata.version("j2live")
        except metadata.PackageNotFoundError:
            version = None
        about_dialog = Gtk.AboutDialog(
            transient_for=self,
            modal=True,
            program_name="j2live",
            version=version,
            comments=_("Live preview for Jinja2 templates"),
        )
        about_dialog.run()
        about_dialog.destroy()

    def on_error_bar_response(self, info_bar, response_id):
        if response_id == RESPONSE_GO_TO_ERROR:
            error = next((e for e in self._errors if e.line is not None), None)
            if error is not None:
                self.go_to_line(self._view_for_error(error), error.line)

    def data_updated(self, buffer: Gtk.TextBuffer):
        """Notify the application that source data has been updated.

        Should be called everytime dependent data for the render
        is updated. It does not necessarily re-render immediately though in order
        to deduplicate the events.
        """
        if self._render_source_id is not None:
            GLib.source_remove(self._render_source_id)
        self._render_source_id = GLib.timeout_add(RENDER_DELAY_MS, self._rerender)

    def _rerender(self):
        if self._render_source_id is not None:
            GLib.source_remove(self._render_source_id)
            self._render_source_id = None

        template = get_text(self.template_buffer)
        data = get_text(self.data_buffer)
        if self.worker is None:
            self._on_render_result(render_plain(template, data))
        else:
            self.worker.render({
                "template": template,
                "data": data,
                "template_path": self._buffer_path(self.template_buffer),
                "data_path": self._buffer_path(self.data_buffer),
            }, self._on_render_result)
            self._set_rendering(True)
        return GLib.SOURCE_REMOVE

    def _set_rendering(self, rendering: bool):
        """Show a spinner for renders slow enough to notice"""
        if rendering:
            if self._spinner_source_id is None and not self.render_spinner.get_visible():
                self._spinner_source_id = GLib.timeout_add(
                    SPINNER_DELAY_MS, self._show_spinner)
            return
        if self._spinner_source_id is not None:
            GLib.source_remove(self._spinner_source_id)
            self._spinner_source_id = None
        self.render_spinner.stop()
        self.render_spinner.hide()

    def _show_spinner(self):
        self._spinner_source_id = None
        self.render_spinner.show()
        self.render_spinner.start()
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _buffer_path(buffer: SourceBuffer) -> Optional[str]:
        gfile = buffer.data.gfile
        return gfile.get_path() if gfile is not None else None

    def _on_render_result(self, result: RenderResult):
        if self.worker is None or not self.worker.busy:
            self._set_rendering(False)
        if result.output is not None:
            self.result_buffer.set_text(result.output)
            log.debug("Re-Rendered results")
        self._show_errors(result.errors)

    def _show_errors(self, errors: list[RenderError]):
        self._errors = errors

        for buffer in (self.template_buffer, self.data_buffer):
            buffer.remove_source_marks(
                buffer.get_start_iter(), buffer.get_end_iter(), ERROR_MARK_CATEGORY)

        if not errors:
            self.error_bar.set_revealed(False)
            self.result_view.set_opacity(1.0)
            return

        for error in errors:
            log.debug("Render failed", error=error.describe())
            if error.line is None:
                continue
            buffer = self._view_for_error(error).get_buffer()
            buffer.create_source_mark(
                None, ERROR_MARK_CATEGORY, buffer.get_iter_at_line(error.line))

        lines = [GLib.markup_escape_text(e.describe()) for e in errors]
        if get_text(self.result_buffer):
            lines.append(
                "<small>" + _("Output is from the last successful render.") + "</small>")
        self.error_label.set_markup("\n".join(lines))
        self.error_goto_button.set_visible(any(e.line is not None for e in errors))
        self.error_bar.set_revealed(True)
        # Dim the output so it's obvious it doesn't reflect the current inputs
        self.result_view.set_opacity(0.5)
