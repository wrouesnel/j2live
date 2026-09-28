"""Main window routines"""
from dataclasses import dataclass
from importlib import metadata
from typing import Callable, Optional

from j2live import logging
from j2live.language_manager import LanguageManager
from j2live.environments import (
    AnsibleWorker, PythonEnvironment, detect_interpreters, interpreter_for_prefix, probe)
from j2live.render import ErrorSource, RenderError, RenderOptions, RenderResult, render_plain
from j2live.ui.editorpane import EditorPane

from gi.repository import Gdk, Gio, Gtk, GLib, GObject, Pango
from gi.repository import GtkSource

from j2live.conf import _

from j2live.util import get_text

log = logging.getLogger()

DEFAULT_WIDTH = 1100
DEFAULT_HEIGHT = 700

# Delay after the last edit before re-rendering, so errors don't flicker
# while a tag is half typed.
RENDER_DELAY_MS = 150

# Renders faster than this don't flash a spinner
SPINNER_DELAY_MS = 250

ERROR_MARK_CATEGORY = "j2live-error"
RESPONSE_GO_TO_ERROR = 1

# Keyboard shortcuts for window actions
ACCELERATORS = {
    "win.open-template": ["<Primary>o"],
    "win.open-data": ["<Primary><Shift>o"],
    "win.save": ["<Primary>s"],
    "win.save-as": ["<Primary><Shift>s"],
    "win.close": ["<Primary>w"],
    "app.quit": ["<Primary>q"],
    "win.go-to-error": ["F8"],
    "win.show-whitespace": ["<Primary><Shift>w"],
}


@dataclass
class LaunchOptions:
    """Command line settings for a new window"""
    template: Optional[str] = None
    data: Optional[str] = None
    # Interpreter or environment directory to render with
    python: Optional[str] = None
    plain: bool = False
    trim_blocks: bool = True
    lstrip_blocks: bool = False
    title: Optional[str] = None


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app, options: Optional[LaunchOptions] = None):
        Gtk.Window.__init__(self, title=_("j2live"), application=app)
        self.options = options or LaunchOptions()
        self.set_size_request(800, 500)
        self.set_default_size(DEFAULT_WIDTH, DEFAULT_HEIGHT)

        # Ansible environment used for rendering; None renders with plain Jinja2
        self.environments: list[PythonEnvironment] = []
        self.environment: Optional[PythonEnvironment] = None
        self.worker: Optional[AnsibleWorker] = None
        self.render_options = RenderOptions(
            trim_blocks=self.options.trim_blocks,
            lstrip_blocks=self.options.lstrip_blocks)

        self._render_source_id = None
        self._errors: list[RenderError] = []
        # Set once the user has agreed to close despite unsaved changes
        self._close_confirmed = False

        self.template_pane = EditorPane(_("Template"), language_id="jinja2")
        self.data_pane = EditorPane(_("Variables"), language_id="yaml")
        self.result_pane = EditorPane(_("Output"), editable=False)
        # The pane Save applies to: whichever editable pane had focus last
        self.active_pane = self.template_pane
        for pane in (self.template_pane, self.data_pane):
            self._setup_error_marks(pane.view)
            pane.view.connect("focus-in-event", self._on_pane_focus, pane)
            pane.buffer.connect("changed", self.data_updated)
            pane.connect("file-state-changed", lambda *args: self._update_title())

        self._setup_actions(app)

        box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL,spacing=0)
        self.add(box)

        box.pack_start(Gtk.MenuBar.new_from_model(self._menu_model()), False, False, 0)
        box.pack_start(self._environment_bar(), False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 0)

        # Template over variables on the left, output on the right
        editorpane = Gtk.Paned.new(Gtk.Orientation.VERTICAL)
        editorpane.set_position((DEFAULT_HEIGHT // 3) * 2)
        editorpane.pack1(self.template_pane, True, False)
        editorpane.pack2(self.data_pane, True, False)

        mainpane = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        mainpane.set_position(DEFAULT_WIDTH // 2)
        mainpane.pack1(editorpane, True, False)
        mainpane.pack2(self._result_pane(), True, False)
        mainpane.set_vexpand(True)
        mainpane.set_hexpand(True)
        box.pack_start(mainpane, True, True, 0)

        self.result_pane.set_show_whitespace(True)

        self._detect_environments()
        self.connect("delete-event", self.on_delete_event)
        self.connect("destroy", lambda *args: self.worker and self.worker.stop())

        # Focus can only be grabbed once the window is mapped
        self.connect("map", lambda *args: self.template_pane.view.grab_focus())

        if self.options.template:
            self.open_template(Gio.File.new_for_commandline_arg(self.options.template))
        if self.options.data:
            self.open_data(Gio.File.new_for_commandline_arg(self.options.data))
        self._update_title()

    # Actions and menus

    def _setup_actions(self, app):
        simple = {
            "open-template": lambda *args: self.on_open_template(),
            "open-data": lambda *args: self.on_open_data(),
            "save": lambda *args: self.active_pane.save(self, self._report_save),
            "save-as": lambda *args: self.active_pane.save_as(self, self._report_save),
            "save-output": lambda *args: self.result_pane.save_as(self, self._report_save),
            "close": lambda *args: self.close(),
            "go-to-error": lambda *args: self.go_to_error(),
            "about": lambda *args: self.on_about(),
            "cut": lambda *args: self._signal_for_focus("cut-clipboard"),
            "copy": lambda *args: self._signal_for_focus("copy-clipboard"),
            "paste": lambda *args: self._signal_for_focus("paste-clipboard"),
        }
        for name, callback in simple.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        toggles = {
            "trim-blocks": (self.render_options.trim_blocks, self._on_trim_blocks),
            "lstrip-blocks": (self.render_options.lstrip_blocks, self._on_lstrip_blocks),
            "show-whitespace": (True, self._on_show_whitespace),
        }
        for name, (initial, callback) in toggles.items():
            action = Gio.SimpleAction.new_stateful(
                name, None, GLib.Variant.new_boolean(initial))
            action.connect("change-state", callback)
            self.add_action(action)

        for action, accels in ACCELERATORS.items():
            app.set_accels_for_action(action, accels)

    def _menu_model(self) -> Gio.Menu:
        def section(*items):
            menu = Gio.Menu()
            for label, action in items:
                menu.append(label, action)
            return menu

        file_menu = Gio.Menu()
        file_menu.append_section(None, section(
            (_("_Open Template…"), "win.open-template"),
            (_("Open _Variables…"), "win.open-data")))
        file_menu.append_section(None, section(
            (_("_Save"), "win.save"),
            (_("Save _As…"), "win.save-as"),
            (_("Save _Output As…"), "win.save-output")))
        file_menu.append_section(None, section(
            (_("_Close"), "win.close"),
            (_("_Quit"), "app.quit")))

        edit_menu = section(
            (_("Cu_t"), "win.cut"),
            (_("_Copy"), "win.copy"),
            (_("_Paste"), "win.paste"))

        view_menu = Gio.Menu()
        view_menu.append_section(None, section(
            (_("Show _Whitespace in Output"), "win.show-whitespace")))
        view_menu.append_section(None, section(
            (_("_Go to Error"), "win.go-to-error")))

        render_menu = section(
            (_("_trim_blocks"), "win.trim-blocks"),
            (_("_lstrip_blocks"), "win.lstrip-blocks"))

        help_menu = section((_("_About"), "win.about"))

        menubar = Gio.Menu()
        menubar.append_submenu(_("_File"), file_menu)
        menubar.append_submenu(_("_Edit"), edit_menu)
        menubar.append_submenu(_("_View"), view_menu)
        menubar.append_submenu(_("_Render"), render_menu)
        menubar.append_submenu(_("_Help"), help_menu)
        return menubar

    def _signal_for_focus(self, signal_name):
        """Emit a clipboard signal on the focused widget, if it has one"""
        widget = self.get_focus()
        if widget is None or not GObject.signal_lookup(signal_name, type(widget)):
            return
        widget.emit(signal_name)

    def _on_trim_blocks(self, action, value):
        action.set_state(value)
        self.render_options.trim_blocks = value.get_boolean()
        self._rerender()

    def _on_lstrip_blocks(self, action, value):
        action.set_state(value)
        self.render_options.lstrip_blocks = value.get_boolean()
        self._rerender()

    def _on_show_whitespace(self, action, value):
        action.set_state(value)
        self.result_pane.set_show_whitespace(value.get_boolean())

    def _on_pane_focus(self, view, event, pane):
        self.active_pane = pane
        return False

    def _update_title(self):
        name = self.template_pane.display_name if self.template_pane.gfile else _("j2live")
        if self.template_pane.modified or self.data_pane.modified:
            name = "• " + name
        if self.options.title:
            name = "%s — %s" % (name, self.options.title)
        elif self.template_pane.gfile:
            name = "%s — j2live" % name
        self.set_title(name)

    # Environment selection

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

        # The template module's whitespace options
        for name, tooltip in (
                ("lstrip-blocks", _("Strip whitespace before block tags on a line")),
                ("trim-blocks", _("Remove the first newline after a block tag"))):
            toggle = Gtk.CheckButton(label=name.replace("-", "_"), tooltip_text=tooltip)
            toggle.set_action_name("win." + name)
            bar.pack_end(toggle, False, False, 0)

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
            detail = _("No Ansible: stock Jinja2 filters and YAML")
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
        elif self._probing(self.environments) and not self.options.plain:
            markup = _("Looking for Ansible…")
            tooltip = None
        else:
            markup = "%s  <span alpha='60%%'>%s</span>" % (
                _("Plain Jinja2"), _("no Ansible environment selected"))
            tooltip = _("Click to choose a Python environment with ansible-core")
        self.environment_label.set_markup(markup)
        self.environment_button.set_tooltip_text(tooltip)

    @staticmethod
    def _probing(environments: list[PythonEnvironment]) -> bool:
        return any(not (e.has_ansible or e.error or e.python_version) for e in environments)

    def _detect_environments(self):
        """Probe likely environments and use the first with ansible-core,
        unless the command line chose one."""
        requested = None
        if self.options.python:
            python = interpreter_for_prefix(self.options.python) or self.options.python
            requested = PythonEnvironment(python)

        self.environments = [PythonEnvironment(python) for python in detect_interpreters()
                             if requested is None or python != requested.python]
        if requested is not None:
            self.environments.insert(0, requested)
        self._refresh_environments()

        def probed(env):
            self._refresh_environments()
            if self.options.plain or self.environment is not None:
                return
            if requested is not None:
                if env is requested:
                    self._select_environment(env)
                    if not env.has_ansible:
                        self._show_message(
                            Gtk.MessageType.ERROR, _("ansible-core is not available"),
                            _("Could not import ansible from %s:\n%s") % (env.python, env.error))
                return
            if self._probing(self.environments):
                return
            found = next((e for e in self.environments if e.has_ansible), None)
            log.info("Detected environments",
                     environments=[(e.python, e.ansible_version) for e in self.environments])
            if found is not None:
                self._select_environment(found)

        for env in self.environments:
            probe(env, probed)

    def _select_environment(self, env: Optional[PythonEnvironment]):
        if env is not None and not env.has_ansible:
            env = None
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
        dialog = Gtk.FileChooserNative.new(
            _("Choose Python Environment"), self,
            Gtk.FileChooserAction.SELECT_FOLDER, _("_Select"), None)
        response = dialog.run()
        prefix = dialog.get_filename()
        dialog.destroy()
        if response == Gtk.ResponseType.ACCEPT and prefix:
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

    # Output and errors

    def _result_pane(self) -> Gtk.Widget:
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
        box.pack_start(self.result_pane, True, True, 0)
        return box

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
            if self._pane_for_error(e).buffer is buffer and e.line == line)

    def _pane_for_error(self, error: RenderError) -> EditorPane:
        if error.source is ErrorSource.DATA:
            return self.data_pane
        return self.template_pane

    def go_to_error(self):
        error = next((e for e in self._errors if e.line is not None), None)
        if error is not None:
            self._pane_for_error(error).go_to_line(error.line)

    def on_error_bar_response(self, info_bar, response_id):
        if response_id == RESPONSE_GO_TO_ERROR:
            self.go_to_error()

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

        template = get_text(self.template_pane.buffer)
        data = get_text(self.data_pane.buffer)
        if self.worker is None:
            self._on_render_result(render_plain(template, data, self.render_options))
        else:
            self.worker.render({
                "template": template,
                "data": data,
                "template_path": self.template_pane.path,
                "data_path": self.data_pane.path,
                "trim_blocks": self.render_options.trim_blocks,
                "lstrip_blocks": self.render_options.lstrip_blocks,
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

    def _on_render_result(self, result: RenderResult):
        if self.worker is None or not self.worker.busy:
            self._set_rendering(False)
        if result.output is not None:
            self.result_pane.buffer.set_text(result.output)
            log.debug("Re-Rendered results")
        self._show_errors(result.errors)

    def _show_errors(self, errors: list[RenderError]):
        self._errors = errors

        for pane in (self.template_pane, self.data_pane):
            buffer = pane.buffer
            buffer.remove_source_marks(
                buffer.get_start_iter(), buffer.get_end_iter(), ERROR_MARK_CATEGORY)

        if not errors:
            self.error_bar.set_revealed(False)
            self.result_pane.view.set_opacity(1.0)
            return

        for error in errors:
            log.debug("Render failed", error=error.describe())
            if error.line is None:
                continue
            buffer = self._pane_for_error(error).buffer
            buffer.create_source_mark(
                None, ERROR_MARK_CATEGORY, buffer.get_iter_at_line(error.line))

        lines = [GLib.markup_escape_text(e.describe()) for e in errors]
        if get_text(self.result_pane.buffer):
            lines.append(
                "<small>" + _("Output is from the last successful render.") + "</small>")
        self.error_label.set_markup("\n".join(lines))
        self.error_goto_button.set_visible(any(e.line is not None for e in errors))
        self.error_bar.set_revealed(True)
        # Dim the output so it's obvious it doesn't reflect the current inputs
        self.result_pane.view.set_opacity(0.5)

    # Files

    def _choose_file(self, title: str) -> Optional[Gio.File]:
        dialog = Gtk.FileChooserNative.new(title, self, Gtk.FileChooserAction.OPEN, None, None)
        response = dialog.run()
        gfile = dialog.get_file()
        dialog.destroy()
        return gfile if response == Gtk.ResponseType.ACCEPT else None

    def _confirm_discard(self, pane: EditorPane) -> bool:
        """Before replacing a pane's contents, check unsaved edits can go"""
        if not pane.modified:
            return True
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=_("Discard unsaved changes to %s?") % pane.display_name)
        dialog.add_buttons(_("_Cancel"), Gtk.ResponseType.CANCEL,
                           _("_Discard"), Gtk.ResponseType.ACCEPT)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.ACCEPT

    def _report_load(self, pane: EditorPane, error: Optional[str]):
        if error is not None:
            self._show_message(Gtk.MessageType.ERROR,
                               _("Could not open %s") % pane.display_name, error)

    def _report_save(self, pane: EditorPane, error: Optional[str]):
        if error is not None and error != _("Cancelled"):
            self._show_message(Gtk.MessageType.ERROR,
                               _("Could not save %s") % pane.display_name, error)

    def open_template(self, gfile: Gio.File):
        # A known file type under the .j2 is probably what the output will be
        rendered = LanguageManager.get_rendered_language(gfile.get_basename())
        if rendered is not None:
            self.result_pane.buffer.set_language(rendered)
        self.template_pane.load(gfile, self._report_load)

    def open_data(self, gfile: Gio.File):
        language = LanguageManager.get_language_from_file(gfile)
        self.data_pane.load(gfile, self._report_load, language=language)

    def on_open_template(self):
        if not self._confirm_discard(self.template_pane):
            return
        gfile = self._choose_file(_("Open Template"))
        if gfile is not None:
            self.open_template(gfile)

    def on_open_data(self):
        if not self._confirm_discard(self.data_pane):
            return
        gfile = self._choose_file(_("Open Variables"))
        if gfile is not None:
            self.open_data(gfile)

    def on_delete_event(self, window, event):
        """Offer to save unsaved changes before the window closes"""
        unsaved = [p for p in (self.template_pane, self.data_pane) if p.modified]
        if not unsaved or self._close_confirmed:
            return False

        names = ", ".join(p.display_name for p in unsaved)
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=_("Save changes to %s before closing?") % names,
            secondary_text=_("Unsaved changes will be lost."))
        dialog.add_buttons(_("Close _without Saving"), Gtk.ResponseType.REJECT,
                           _("_Cancel"), Gtk.ResponseType.CANCEL,
                           _("_Save"), Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.REJECT:
            self._close_confirmed = True
            return False
        if response == Gtk.ResponseType.ACCEPT:
            self._save_all(unsaved, self._close_after_save)
        return True

    def _save_all(self, panes: list[EditorPane], on_done: Callable[[bool], None]):
        """Save panes one after another, stopping at the first failure"""
        if not panes:
            on_done(True)
            return

        def saved(pane, error):
            self._report_save(pane, error)
            if error is not None:
                on_done(False)
            else:
                self._save_all(panes[1:], on_done)

        panes[0].save(self, saved)

    def _close_after_save(self, ok: bool):
        if ok:
            self._close_confirmed = True
            self.close()

    def _show_message(self, message_type: Gtk.MessageType, text: str, secondary: str):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=message_type,
            buttons=Gtk.ButtonsType.CLOSE, text=text, secondary_text=secondary)
        dialog.run()
        dialog.destroy()

    def on_about(self):
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
