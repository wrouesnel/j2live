# Copyright (C) 2002-2006 Stephen Kennedy <stevek@gnome.org>
# Copyright (C) 2009-2013 Kai Willadsen <kai.willadsen@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or (at
# your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Adapted by Will Rouesnel (2026)

import enum
from typing import Optional

from gi.repository import Gio, GLib, GObject, GtkSource

from j2live import logging
log = logging.get_logger()

class SourceBuffer(GtkSource.Buffer):

    __gtype_name__ = "SourceBuffer"

    __gsettings_bindings__ = (
        ('highlight-syntax', 'highlight-syntax'),
    )

    def __init__(self):
        super().__init__()
        #bind_settings(self) # TODO
        self.data = SourceBufferData()
        self.undo_sequence = None

    def do_begin_user_action(self, *args):
        if self.undo_sequence:
            self.undo_sequence.begin_group()

    def do_end_user_action(self, *args):
        if self.undo_sequence:
            self.undo_sequence.end_group()

    def get_iter_at_line_or_eof(self, line):
        """Return a Gtk.TextIter at the given line, or the end of the buffer.

        This method is like get_iter_at_line, but if asked for a position past
        the end of the buffer, this returns the end of the buffer; the
        get_iter_at_line behaviour is to return the start of the last line in
        the buffer.
        """
        if line >= self.get_line_count():
            return self.get_end_iter()
        return self.get_iter_at_line(line)

    def insert_at_line(self, line, text):
        """Insert text at the given line, or the end of the buffer.

        This method is like insert, but if asked to insert something past the
        last line in the buffer, this will insert at the end, and will add a
        linebreak before the inserted text. The last line in a Gtk.TextBuffer
        is guaranteed never to have a newline, so we need to handle this.
        """
        if line >= self.get_line_count():
            # TODO: We need to insert a linebreak here, but there is no
            # way to be certain what kind of linebreak to use.
            text = "\n" + text
        it = self.get_iter_at_line_or_eof(line)
        self.insert(it, text)
        return it

class SourceBufferState(enum.Enum):
    EMPTY = "EMPTY"
    LOADING = "LOADING"
    LOAD_FINISHED = "LOAD_FINISHED"
    LOAD_ERROR = "LOAD_ERROR"


class SourceBufferData(GObject.GObject):

    state: SourceBufferState

    @GObject.Signal('file-changed')
    def file_changed_signal(self) -> None:
        ...

    encoding = GObject.Property(
        type=GtkSource.Encoding,
        nick="The file encoding of the linked GtkSourceFile",
        default=GtkSource.Encoding.get_utf8(),
    )

    def __init__(self):
        super().__init__()
        self._gfile = None
        self._label = None
        self._monitor = None
        self._sourcefile = None
        self.reset(gfile=None, state=SourceBufferState.EMPTY)

    def reset(self, gfile: Optional[Gio.File], state: SourceBufferState):
        same_file = gfile and self._gfile and gfile.equal(self._gfile)
        self.gfile = gfile
        if same_file:
            self.label = self._label
        else:
            self.label = gfile.get_parse_name() if gfile else None
        self.state = state
        self.savefile = None

    def __del__(self):
        self.disconnect_monitor()

    @property
    def label(self):
        # TRANSLATORS: This is the label of a new, currently-unnamed file.
        return self._label or _("<unnamed>")

    @label.setter
    def label(self, value):
        if not value:
            return
        if not isinstance(value, str):
            log.warning('Invalid label ignored "%r"', value)
            return
        self._label = value

    def connect_monitor(self):
        if not self._gfile:
            return
        monitor = self._gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        handler_id = monitor.connect('changed', self._handle_file_change)
        self._monitor = monitor, handler_id

    def disconnect_monitor(self):
        if not self._monitor:
            return
        monitor, handler_id = self._monitor
        monitor.disconnect(handler_id)
        monitor.cancel()
        self._monitor = None

    def _query_mtime(self, gfile):
        try:
            time_query = ",".join((Gio.FILE_ATTRIBUTE_TIME_MODIFIED,
                                   Gio.FILE_ATTRIBUTE_TIME_MODIFIED_USEC))
            info = gfile.query_info(time_query, 0, None)
        except GLib.GError:
            return None
        mtime = info.get_modification_time()
        return (mtime.tv_sec, mtime.tv_usec)

    def _handle_file_change(self, monitor, f, other_file, event_type):
        mtime = self._query_mtime(f)
        if self._disk_mtime and mtime and mtime > self._disk_mtime:
            self.file_changed_signal.emit()
        self._disk_mtime = mtime or self._disk_mtime

    @property
    def gfile(self):
        return self._gfile

    @gfile.setter
    def gfile(self, value):
        self.disconnect_monitor()
        self._gfile = value
        self._sourcefile = GtkSource.File()
        self._sourcefile.set_location(value)
        self._sourcefile.bind_property(
            'encoding', self, 'encoding', GObject.BindingFlags.DEFAULT)

        self.update_mtime()
        self.connect_monitor()

    @property
    def sourcefile(self):
        return self._sourcefile

    @property
    def gfiletarget(self):
        return self.savefile or self.gfile

    @property
    def is_special(self):
        try:
            info = self._gfile.query_info(
                Gio.FILE_ATTRIBUTE_STANDARD_TYPE, 0, None)
            return info.get_file_type() == Gio.FileType.SPECIAL
        except (AttributeError, GLib.GError):
            return False

    @property
    def file_id(self) -> Optional[str]:
        try:
            info = self._gfile.query_info(Gio.FILE_ATTRIBUTE_ID_FILE, 0, None)
            return info.get_attribute_string(Gio.FILE_ATTRIBUTE_ID_FILE)
        except (AttributeError, GLib.GError):
            return None

    @property
    def writable(self):
        try:
            info = self.gfiletarget.query_info(
                Gio.FILE_ATTRIBUTE_ACCESS_CAN_WRITE, 0, None)
        except GLib.GError as err:
            if err.code == Gio.IOErrorEnum.NOT_FOUND:
                return True
            return False
        except AttributeError:
            return False
        return info.get_attribute_boolean(Gio.FILE_ATTRIBUTE_ACCESS_CAN_WRITE)

    def update_mtime(self):
        if self._gfile:
            self._disk_mtime = self._query_mtime(self._gfile)
            self._mtime = self._disk_mtime

    def current_on_disk(self):
        return self._mtime == self._disk_mtime