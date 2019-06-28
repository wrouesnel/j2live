"""Utility functions"""

from gi.repository import Gtk

def get_text(buffer : Gtk.TextBuffer):
    """Get the full content of a GtkTextBuffer"""
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
