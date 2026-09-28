"""Discovery of Python environments with ansible-core, and the render worker
process that runs inside one."""
import json
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Callable, Optional

from gi.repository import Gio, GLib

from j2live import logging
from j2live.conf import _
from j2live.render import ErrorSource, RenderError, RenderResult

log = logging.getLogger()

WORKER_SCRIPT = os.path.join(os.path.dirname(__file__), "ansible_worker.py")

# A template like range(10**9) must not wedge the preview forever
RENDER_TIMEOUT_MS = 5000


@dataclass
class PythonEnvironment:
    """A Python interpreter, as reported by the worker's --probe hello"""
    python: str
    prefix: Optional[str] = None
    python_version: Optional[str] = None
    ansible_version: Optional[str] = None
    error: Optional[str] = None

    @property
    def has_ansible(self) -> bool:
        return self.ansible_version is not None

    @property
    def display_prefix(self) -> str:
        path = self.prefix or self.python
        home = os.path.expanduser("~")
        if path == home or path.startswith(home + os.sep):
            return "~" + path[len(home):]
        return path

    def update_from_hello(self, hello: dict):
        self.prefix = hello.get("prefix")
        self.python_version = hello.get("python_version")
        self.ansible_version = hello.get("ansible_version")
        self.error = hello.get("error")


def _own_environment(path: str) -> bool:
    """Is this path inside j2live's own environment (e.g. set by uv run)?"""
    prefix = os.path.realpath(sys.prefix)
    return os.path.realpath(path).startswith(prefix + os.sep)


def _which_outside_own(name: str) -> Optional[str]:
    """Find an executable on PATH, skipping our own environment's bin dir"""
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory or _own_environment(os.path.join(directory, name)):
            continue
        found = shutil.which(name, path=directory)
        if found:
            return found
    return None


def _shebang_interpreter(script: str) -> Optional[str]:
    try:
        with open(script, "rb") as f:
            first = f.readline(4096).decode("utf-8", "replace").strip()
    except OSError:
        return None
    if not first.startswith("#!"):
        return None
    parts = first[2:].split()
    if not parts:
        return None
    if os.path.basename(parts[0]) == "env" and len(parts) > 1:
        return _which_outside_own(parts[-1])
    return parts[0]


def interpreter_for_prefix(prefix: str) -> Optional[str]:
    """Find the interpreter of an environment directory"""
    for name in ("bin/python3", "bin/python", "Scripts/python.exe"):
        candidate = os.path.join(prefix, name)
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def detect_interpreters() -> list[str]:
    """Interpreters that might hold ansible-core, most likely first.

    The "active" environment is an activated virtualenv or conda env, then
    whatever the ansible on PATH runs under, then python3 on PATH.
    """
    candidates = []
    for var in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        prefix = os.environ.get(var)
        if prefix and not _own_environment(os.path.join(prefix, "bin")):
            candidates.append(interpreter_for_prefix(prefix))

    for tool in ("ansible", "ansible-playbook"):
        script = _which_outside_own(tool)
        if script:
            candidates.append(_shebang_interpreter(os.path.realpath(script)))

    candidates.append(_which_outside_own("python3"))

    seen = set()
    result = []
    for candidate in candidates:
        if candidate and candidate not in seen and not _own_environment(candidate):
            seen.add(candidate)
            result.append(candidate)
    return result


def _spawn_worker(python: str, *args: str) -> Gio.Subprocess:
    # The script's directory isn't safe to have on sys.path, and the worker
    # removes it itself; the cwd is irrelevant to it.
    return Gio.Subprocess.new(
        [python, "-u", WORKER_SCRIPT, *args],
        Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE)


def probe(env: PythonEnvironment, callback: Callable[[PythonEnvironment], None]):
    """Fill in env details asynchronously by running the worker with --probe"""
    try:
        proc = _spawn_worker(env.python, "--probe")
    except GLib.Error as e:
        env.error = e.message
        GLib.idle_add(lambda: callback(env))
        return

    def done(proc, result):
        try:
            _, stdout, _ = proc.communicate_utf8_finish(result)
            env.update_from_hello(json.loads(stdout.splitlines()[0]))
        except (GLib.Error, ValueError, IndexError) as e:
            env.error = getattr(e, "message", None) or str(e)
        callback(env)

    proc.communicate_utf8_async(None, None, done)


class AnsibleWorker:
    """A long-lived worker process rendering templates with ansible-core.

    Only one request is in flight at a time; requests made while busy replace
    any queued one, since only the latest inputs matter.
    """

    def __init__(self, env: PythonEnvironment):
        self.env = env
        self._proc: Optional[Gio.Subprocess] = None
        self._stdout: Optional[Gio.DataInputStream] = None
        self._cancellable: Optional[Gio.Cancellable] = None
        self._ready = False
        self._in_flight: Optional[Callable] = None
        self._queued: Optional[tuple[dict, Callable]] = None
        self._timeout_id = None

    @property
    def busy(self) -> bool:
        return self._in_flight is not None or self._queued is not None

    def _start(self):
        self._cancellable = Gio.Cancellable()
        self._proc = _spawn_worker(self.env.python)
        self._stdout = Gio.DataInputStream.new(self._proc.get_stdout_pipe())
        self._ready = False
        self._stdout.read_line_async(
            GLib.PRIORITY_DEFAULT, self._cancellable, self._on_hello)

    def stop(self):
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None
        if self._cancellable is not None:
            self._cancellable.cancel()
        if self._proc is not None:
            self._proc.force_exit()
        self._proc = self._stdout = self._cancellable = None
        self._ready = False

    def _read_json(self, stream, result) -> Optional[dict]:
        line, _ = stream.read_line_finish_utf8(result)
        if line is None:
            return None
        return json.loads(line)

    def _fail(self, message: str, retry_queued: bool = False):
        """Report the failure to whoever is waiting and restart on next use.

        With retry_queued a queued request gets a fresh worker instead of the
        error, since it may well not share the problem (e.g. a timeout).
        """
        log.error("Ansible worker failed", python=self.env.python, error=message)
        waiting = [self._in_flight] if self._in_flight else []
        queued = self._queued
        if queued and not retry_queued:
            waiting.append(queued[1])
            queued = None
        self._in_flight = self._queued = None
        self.stop()
        for callback in waiting:
            callback(RenderResult(errors=[RenderError(ErrorSource.RENDER, message)]))
        if queued:
            self.render(*queued)

    def _on_hello(self, stream, result):
        try:
            hello = self._read_json(stream, result)
        except GLib.Error as e:
            if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                return
            return self._fail(_("Ansible environment failed to start: %s") % e.message)
        if hello is None:
            return self._fail(_("Ansible environment exited during startup"))
        if hello.get("error"):
            return self._fail(_("Could not load ansible-core: %s") % hello["error"])
        self._ready = True
        self._send_queued()

    def render(self, request: dict, callback: Callable[[RenderResult], None]):
        self._queued = (request, callback)
        if self._proc is None:
            try:
                self._start()
            except GLib.Error as e:
                self._fail(_("Could not start %s: %s") % (self.env.python, e.message))
            return
        self._send_queued()

    def _send_queued(self):
        if not self._ready or self._in_flight or not self._queued:
            return
        request, callback = self._queued
        self._queued = None
        self._in_flight = callback
        try:
            self._proc.get_stdin_pipe().write_all(
                (json.dumps(request) + "\n").encode("utf-8"), None)
        except GLib.Error as e:
            return self._fail(_("Ansible environment stopped: %s") % e.message)
        self._timeout_id = GLib.timeout_add(RENDER_TIMEOUT_MS, self._on_timeout)
        self._stdout.read_line_async(
            GLib.PRIORITY_DEFAULT, self._cancellable, self._on_response)

    def _on_timeout(self):
        self._timeout_id = None
        self._fail(_("Rendering took longer than %d seconds and was stopped")
                   % (RENDER_TIMEOUT_MS // 1000), retry_queued=True)
        return GLib.SOURCE_REMOVE

    def _on_response(self, stream, result):
        try:
            response = self._read_json(stream, result)
        except GLib.Error as e:
            if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                return
            return self._fail(_("Ansible environment stopped: %s") % e.message)
        if response is None:
            return self._fail(_("Ansible environment exited unexpectedly"))

        GLib.source_remove(self._timeout_id)
        self._timeout_id = None
        callback, self._in_flight = self._in_flight, None
        callback(RenderResult(
            output=response.get("output"),
            errors=[RenderError.from_json(e) for e in response.get("errors", [])]))
        self._send_queued()
