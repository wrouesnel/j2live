# -*- coding: utf-8 -*-
"""Open a template in j2live on the controller, then deploy it with template.

A drop-in replacement for ansible.builtin.template. Before templating, the
template source is opened in j2live with the host's variables, rendering with
the same ansible-core and whitespace options the task will use. The play
waits until the j2live window is closed, then runs the normal template action
with whatever was saved, so a template can be fixed up while the playbook is
running.
"""
from __future__ import annotations

DOCUMENTATION = r"""
action: j2live_template
short_description: Live edit a template in j2live, then template it
description:
  - Accepts every option of M(ansible.builtin.template), plus the options below.
  - Opens the template source in j2live on the controller, with the host's
    variables, and waits for the window to close before templating.
  - Variables edited in j2live are only for experimenting; the playbook
    always uses its own variables. Saving the template in j2live writes the
    real template source, which is what gets deployed.
  - With no display (C(DISPLAY)/C(WAYLAND_DISPLAY) unset) or with C(J2LIVE=0)
    in the environment, j2live is skipped and this behaves exactly like
    M(ansible.builtin.template).
options:
  j2live:
    description: Open j2live. Defaults to on unless C(J2LIVE=0) is set.
    type: bool
  j2live_once:
    description:
      - Only open j2live for the first host to reach the task, per template
        source and playbook run. Other hosts wait for it and then use the
        saved template.
      - When false, j2live is opened for each host in turn.
    type: bool
    default: true
  j2live_command:
    description: Command to run j2live, defaulting to C(J2LIVE_COMMAND) or C(j2live).
    type: str
  j2live_exclude_vars:
    description: Variables not to pass to j2live, in addition to C(hostvars), C(vars) and C(omit).
    type: list
    elements: str
    default: []
"""

EXAMPLES = r"""
- name: Deploy nginx config, fixing the template up live
  j2live_template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    mode: "0644"
"""

import datetime
import fcntl
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Set

import yaml

from ansible.errors import AnsibleActionFail, AnsibleError
from ansible.module_utils.common.text.converters import to_text
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.action import ActionBase
from ansible.utils.display import Display

display = Display()

J2LIVE_OPTIONS = ("j2live", "j2live_once", "j2live_command", "j2live_exclude_vars")

# Too big or too internal to be useful in a variables file
EXCLUDED_VARS = {"hostvars", "vars", "omit", "environment"}

TEMPLATE_MARKERS = ("{{", "{%", "{#")


class _Unsafe(str):
    """A resolved string that j2live must not template again"""


class _VarsDumper(yaml.SafeDumper):
    pass


_VarsDumper.add_representer(
    _Unsafe, lambda dumper, data: dumper.represent_scalar("!unsafe", str(data)))


def _is_data(value):
    """Plain data, as opposed to objects ansible exposes as variables"""
    return isinstance(value, (str, int, float, bool, type(None), datetime.date,
                              Mapping, list, tuple, Set))


def _exact_str(value):
    """A plain str copy; ansible's str subclasses can't be safely dumped"""
    return value.encode("utf-8", "surrogatepass").decode("utf-8", "surrogatepass")


def _plain(value, resolved):
    """Reduce ansible's variable types to what safe YAML can represent.

    Resolved strings still containing template markers were meant to be
    literal (e.g. !unsafe), so they are tagged to stay that way in j2live.
    """
    if isinstance(value, str):
        text = _exact_str(value)
        if resolved and any(marker in text for marker in TEMPLATE_MARKERS):
            return _Unsafe(text)
        return text
    if isinstance(value, bool) or value is None:
        return bool(value) if value is not None else None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value
    if isinstance(value, Mapping):
        return {_exact_str(to_text(k)): _plain(v, resolved) for k, v in value.items()}
    if isinstance(value, (list, tuple, Set)):
        return [_plain(v, resolved) for v in value]
    return _exact_str(to_text(value))


class ActionModule(ActionBase):

    _supports_check_mode = True
    _supports_async = False

    def run(self, tmp=None, task_vars=None):
        task_vars = task_vars or {}
        args = dict(self._task.args)
        options = {name: args.pop(name, None) for name in J2LIVE_OPTIONS}

        enabled = options["j2live"]
        if enabled is None:
            enabled = boolean(os.environ.get("J2LIVE", "1"), strict=False)
        if boolean(enabled, strict=False):
            self._live_edit(args, options, task_vars)

        return self._run_template(args, task_vars)

    def _run_template(self, args, task_vars):
        task = self._task.copy()
        task.args = args
        action = self._shared_loader_obj.action_loader.get(
            "ansible.builtin.template",
            task=task,
            connection=self._connection,
            play_context=self._play_context,
            loader=self._loader,
            templar=self._templar,
            shared_loader_obj=self._shared_loader_obj,
        )
        return action.run(task_vars=task_vars)

    def _live_edit(self, args, options, task_vars):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            display.warning("j2live_template: no display available, skipping j2live")
            return

        src = args.get("src")
        if not src:
            # Let the template action report the missing argument
            return
        try:
            source = self._find_needle("templates", src)
        except AnsibleError as e:
            raise AnsibleActionFail(to_text(e))

        command = options["j2live_command"] or os.environ.get("J2LIVE_COMMAND", "j2live")
        argv = shlex.split(command)
        if not shutil.which(argv[0]):
            display.warning("j2live_template: %r not found, skipping j2live" % argv[0])
            return

        once = boolean(options["j2live_once"] if options["j2live_once"] is not None else True,
                       strict=False)
        state_dir = os.path.join(tempfile.gettempdir(), "j2live-ansible-%d" % os.getppid())
        os.makedirs(state_dir, mode=0o700, exist_ok=True)
        key = hashlib.sha1(source.encode("utf-8")).hexdigest()
        done_marker = os.path.join(state_dir, key + ".done")

        # Workers run in parallel; show one window at a time, and with
        # j2live_once only the first host gets one.
        with open(os.path.join(state_dir, key + ".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if once and os.path.exists(done_marker):
                return
            self._open_j2live(argv, source, args, options, task_vars, state_dir)
            if once:
                open(done_marker, "w").close()

    def _open_j2live(self, argv, source, args, options, task_vars, state_dir):
        host = task_vars.get("inventory_hostname", "")
        exclude = EXCLUDED_VARS | set(options["j2live_exclude_vars"] or ())

        fd, vars_path = tempfile.mkstemp(
            prefix="%s-" % (host or "vars"), suffix=".yml", dir=state_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("# Variables of %s for %s, captured by j2live_template.\n"
                        "# Edits here are for experimenting only; the playbook "
                        "uses its own variables.\n" % (host, os.path.basename(source)))
                yaml.dump(self._variables(task_vars, exclude), f, Dumper=_VarsDumper,
                          default_flow_style=False, allow_unicode=True, sort_keys=True)

            command = argv + [
                source,
                "--data", vars_path,
                # Render with this ansible-core, exactly as the task will
                "--python", sys.executable,
                "--trim-blocks" if boolean(args.get("trim_blocks", True), strict=False)
                else "--no-trim-blocks",
                "--lstrip-blocks" if boolean(args.get("lstrip_blocks", False), strict=False)
                else "--no-lstrip-blocks",
                "--title", "%s · %s" % (host, self._task.get_name()),
            ]
            display.display(
                "j2live: editing %s for %s; close the window to continue" % (source, host),
                color="bright blue")
            display.vvv("j2live: %s" % " ".join(shlex.quote(c) for c in command))
            try:
                result = subprocess.run(command, stdin=subprocess.DEVNULL)
            except OSError as e:
                display.warning("j2live_template: could not run j2live: %s" % e)
                return
            if result.returncode != 0:
                display.warning("j2live_template: j2live exited with status %d"
                                % result.returncode)
        finally:
            os.unlink(vars_path)

    def _variables(self, task_vars, exclude):
        """Resolve the host's variables to plain values for j2live"""
        templar = self._templar.copy_with_new_env(available_variables=task_vars)
        variables = {}
        for name in sorted(task_vars, key=str):
            if name in exclude:
                continue
            raw = task_vars[name]
            if not _is_data(raw):
                continue
            try:
                variables[_exact_str(name)] = _plain(templar.template(raw), resolved=True)
            except Exception as e:
                # Leave it for j2live to report if the template uses it
                display.vvv("j2live_template: could not resolve %s: %s" % (name, e))
                try:
                    variables[_exact_str(name)] = _plain(raw, resolved=False)
                except Exception:
                    pass
        return variables
