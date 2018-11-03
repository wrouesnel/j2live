"""Utility functions"""

import jinja2

from gi.repository import Gtk

def template_from_string(text : str) -> jinja2.Template:
    """Load a Jinja2 template from a string"""
    return jinja2.Environment(loader=jinja2.BaseLoader()).from_string(text)

def get_text(buffer : Gtk.TextBuffer):
    """Get the full content of a GtkTextBuffer"""
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)