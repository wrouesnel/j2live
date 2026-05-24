
from gi.repository import GtkSource
def get_custom_encoding_candidates():
    custom_candidates = []
    custom_candidates.extend(
        GtkSource.Encoding.get_default_candidates())
    return custom_candidates