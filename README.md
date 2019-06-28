# Live Jinja2 Editor

A simple GTK application for live-editing of Jinja2 templates.

## Reason

Jinja2's rules aren't the easiest to understand at times, particularly
when it comes to editing whitespace. After going round this loop with
Ansible a few times, and finding a web-based version [here](https://github.com/qn7o/jinja2-live-parser)
I decided to try and build something I could run locally.

## Templating Engine

The default templating engine is Ansible's `Templar` class, which provides access to the full
Ansible built-in templating engine. You can use any standard Ansible Jinja2 syntax. It does
not currently detect Ansible projects and load plugins however (coming soon!)