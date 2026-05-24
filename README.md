# Live Jinja2 Editor

A simple GTK application for live-editing of Jinja2 templates.

## Reason

Jinja2's rules aren't the easiest to understand at times, particularly
when it comes to editing whitespace. After going round this loop with
Ansible a few times, and finding a web-based version [here](https://github.com/qn7o/jinja2-live-parser)
I decided to try and build something I could run locally.

## Installation and Running

This isn't properly developed, but it works for it's basic function.

Ubuntu:

```
sudo apt install libcairo2-dev libgirepository-2.0-dev gir1.2-gtk-3.0
uv run j2live
```

## Acknowledgements

The UI elements are wholesale borrowed from the [Meld](https://gitlab.gnome.org/GNOME/meld).
All rights to that code belong to them.