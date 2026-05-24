"""
Borrowed from meld as well
"""

from gi.repository import GtkSource, Gio, GLib

class LanguageManager:

    manager = GtkSource.LanguageManager()

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
