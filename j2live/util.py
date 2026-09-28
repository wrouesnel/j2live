"""Utility functions"""

import jinja2

from gi.repository import Gtk

def template_from_string(text : str, **options) -> jinja2.Template:
    """Load a Jinja2 template from a string, with Environment options"""
    return jinja2.Environment(loader=jinja2.BaseLoader(), **options).from_string(text)

def get_text(buffer : Gtk.TextBuffer):
    """Get the full content of a GtkTextBuffer"""
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)