# j2live_template: live edit templates while a playbook runs

`j2live_template` is a drop-in replacement for `ansible.builtin.template`.
When the task runs, it opens the template source in j2live on the controller,
with the host's variables, and pauses the play until you close the window. It
then runs the normal `template` action, so whatever you saved is what gets
deployed.

j2live renders with the controller's own ansible-core and the task's
`trim_blocks`/`lstrip_blocks`, so the preview matches what the task will write.

```yaml
- name: Deploy nginx config
  j2live_template:          # instead of ansible.builtin.template
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    mode: "0644"
```

## Setup

1. Install j2live on the controller so `j2live` is on your `PATH`
   (e.g. `uv tool install /path/to/j2live`), or set `J2LIVE_COMMAND`.
2. Make the action plugin available to your playbooks, either by pointing
   `action_plugins` in `ansible.cfg` at `extras/ansible/action_plugins`, or by
   copying `j2live_template.py` into an `action_plugins/` directory next to
   your playbook or into a role or collection.

Try it with the example: `cd example && ansible-playbook playbook.yml`.

## Behaviour

- **Variables** are the host's variables at that task, resolved, written to a
  temporary file. `hostvars`, `vars` and `omit` are left out, as is anything in
  `j2live_exclude_vars`. Editing them in j2live is handy for experimenting, but
  the playbook always uses its real variables.
- **The template** is the real source file, found the same way `template`
  finds it (roles, `templates/` directories). Saving in j2live changes it on
  disk.
- **Many hosts:** by default j2live opens once per template per playbook run,
  for the first host to reach the task; the other hosts wait for it and then
  use the saved template. Set `j2live_once: false` to get a window for each
  host in turn.
- **Headless runs:** with no display (`DISPLAY`/`WAYLAND_DISPLAY` unset), with
  `J2LIVE=0`, or with `j2live: false` on the task, j2live is skipped and the
  task behaves exactly like `template`. That makes it safe to leave in
  playbooks that also run in CI.

## Options

All `ansible.builtin.template` options, plus:

| Option | Default | Description |
| --- | --- | --- |
| `j2live` | on unless `J2LIVE=0` | Open j2live at all |
| `j2live_once` | `true` | Only open j2live for the first host per template |
| `j2live_command` | `$J2LIVE_COMMAND` or `j2live` | Command to run j2live |
| `j2live_exclude_vars` | `[]` | More variables to leave out of the variables file |
