"""Constants for j2live (following the pattern of meld)"""

__package__ = "j2live"
__version__ = "0.0.1"

APPLICATION_ID = "com.wrouesnel.j2live"

PYTHON_REQUIREMENT_TUPLE = (3, 6)

# Installed from main script
def no_translation(gettext_string, *args):
    return gettext_string


_ = no_translation
ngettext = no_translation