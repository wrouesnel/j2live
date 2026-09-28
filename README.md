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
sudo apt install libcairo2-dev libgirepository-2.0-dev gir1.2-gtk-3.0 gir1.2-gtksource-4
uv run j2live
```

Or install it as a tool with `uv tool install .`

## Usage

```
j2live [TEMPLATE] [-d VARS.yml] [--python ENV | --plain]
       [--[no-]trim-blocks] [--[no-]lstrip-blocks] [--title TEXT]
```

The template is on the left, its variables (YAML) below it, and the rendered
output on the right with whitespace made visible. Errors are shown above the
output and marked on the offending line; <kbd>F8</kbd> jumps to the first one.
Files changed on disk are reloaded, or offered for reloading if you have edits.

| Shortcut | Action |
| --- | --- |
| <kbd>Ctrl</kbd>+<kbd>O</kbd> / <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>O</kbd> | Open template / variables |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> / <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd> | Save / save as (the last focused pane) |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>W</kbd> | Toggle visible whitespace in the output |
| <kbd>F8</kbd> | Go to error |
| <kbd>Ctrl</kbd>+<kbd>W</kbd> / <kbd>Ctrl</kbd>+<kbd>Q</kbd> | Close / quit |

## Ansible

Templates render the way Ansible's `template` module renders them (its
`trim_blocks`/`lstrip_blocks` options, which are toggles at the top right,
Ansible's filters and YAML loading, `#jinja2:` override headers) using the
ansible-core installed in a Python environment of your choosing. The environment
in use is shown at the top of the window; click it to switch.

On startup j2live picks the first of these that has ansible-core:

1. the activated virtualenv or conda environment
2. the interpreter the `ansible` command on your `PATH` runs under
3. `python3` on your `PATH`

If none do, templates render with plain Jinja2 defaults.

## Acknowledgements

The UI elements are wholesale borrowed from the [Meld](https://gitlab.gnome.org/GNOME/meld).
All rights to that code belong to them.