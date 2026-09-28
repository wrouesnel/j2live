"""
Borrowed from meld as well
"""

import os

from gi.repository import GtkSource, Gio, GLib

LANGUAGE_SPECS_DIR = os.path.join(os.path.dirname(__file__), "resources", "language-specs")

# Extensions that mark a file as a template of some other kind of file
TEMPLATE_SUFFIXES = (".j2", ".jinja", ".jinja2")


def _new_manager() -> GtkSource.LanguageManager:
    manager = GtkSource.LanguageManager()
    manager.set_search_path([LANGUAGE_SPECS_DIR, *manager.get_search_path()])
    return manager


class LanguageManager:

    manager = _new_manager()

    @classmethod
    def get_language(cls, language_id):
        return cls.manager.get_language(language_id)

    @classmethod
    def get_rendered_language(cls, template_name):
        """Guess the language a template renders to, e.g. nginx.conf.j2 -> nginx"""
        root, ext = os.path.splitext(template_name)
        if ext.lower() not in TEMPLATE_SUFFIXES:
            return None
        return cls.manager.guess_language(root, None)

    @classmethod
    def get_language_from_file(cls, gfile):
        try:
            info = gfile.query_info(
                Gio.FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE, 0, None)
        except (GLib.GError, AttributeError):
            return None
        content_type = info.get_content_type()
        return cls.manager.guess_language(gfile.get_basename(), content_type)

    @classmethod
    def get_language_from_mime_type(cls, mime_type):
        content_type = Gio.content_type_from_mime_type(mime_type)
        return cls.manager.guess_language(None, content_type)
