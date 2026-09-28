"""Render worker run under the interpreter of the selected Ansible environment.

This file is executed as a standalone script by *another* Python, so it must
only import the standard library and ansible, and must stay compatible with
the oldest Python ansible-core supports.

Protocol: one JSON object per line.
  -> {"template": str, "data": str,
      "template_path": str|null, "data_path": str|null,
      "trim_blocks": bool, "lstrip_blocks": bool}
  <- {"output": str|null, "errors": [{"source", "message", "line"}]}
On startup a hello line is written:
  <- {"python": str, "prefix": str, "python_version": str,
      "ansible_version": str|null, "error": str|null}
With --probe the worker exits after the hello.
"""
import sys

# Running as a script puts j2live/ on the path, where our logging.py would
# shadow the stdlib module ansible depends on.
del sys.path[0]

import io
import json
import os
import re

# Anything ansible prints must not corrupt the protocol stream, so keep a
# private handle to stdout and point the regular one at stderr.
_protocol = io.open(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
sys.stdout = sys.stderr

_UNDEFINED_RE = re.compile(r"'(\w+)' is undefined")
_TAG_RE = re.compile(r"{{.*?}}|{%.*?%}")


def _send(obj):
    _protocol.write(json.dumps(obj) + "\n")
    _protocol.flush()


def _hello():
    hello = {
        "python": sys.executable,
        "prefix": sys.prefix,
        "python_version": "%d.%d.%d" % sys.version_info[:3],
        "ansible_version": None,
        "error": None,
    }
    try:
        from ansible.release import __version__
        hello["ansible_version"] = __version__
    except Exception as e:
        hello["error"] = "%s: %s" % (type(e).__name__, e)
    return hello


def _exception_chain(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or getattr(exc, "orig_exc", None) or exc.__context__


def _error(source, message, line=None):
    return {"source": source, "message": message, "line": line}


def _jinja_line(exc):
    """Map the innermost compiled-template frame back to a template line.

    Jinja normally rewrites tracebacks to template lines itself, but ansible
    catches exceptions before that happens.
    """
    line = None
    tb = exc.__traceback__
    while tb is not None:
        template = tb.tb_frame.f_globals.get("__jinja_template__")
        if template is not None:
            line = template.get_corresponding_lineno(tb.tb_lineno) - 1
        tb = tb.tb_next
    return line


def _undefined_line(message, text):
    """Best guess at where an undefined variable is used.

    Newer ansible reports undefined variables without any traceback into the
    template, so fall back to the first expression mentioning the name.
    """
    match = _UNDEFINED_RE.search(message)
    if not match:
        return None
    name = re.compile(r"\b%s\b" % re.escape(match.group(1)))
    for number, line in enumerate(text.splitlines()):
        if any(name.search(tag) for tag in _TAG_RE.findall(line)):
            return number
    return None


def _template_error(exc, text):
    """Classify a templating exception, digging out the template line."""
    import jinja2

    chain = list(_exception_chain(exc))
    for e in chain:
        if isinstance(e, jinja2.TemplateSyntaxError):
            line = e.lineno - 1 if e.lineno else None
            return _error("template", e.message or str(e), line)

    line = None
    for e in chain:
        line = _jinja_line(e)
        if line is not None:
            break
    message = (getattr(exc, "message", None) or str(exc) or type(exc).__name__).strip()
    if line is None:
        line = _undefined_line(message, text)
    return _error("render", message, line)


def _yaml_mark(exc):
    for e in _exception_chain(exc):
        mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
        if mark is not None:
            problem = getattr(e, "problem", None) or str(e)
            context = getattr(e, "context", None)
            context_mark = getattr(e, "context_mark", None)
            if context and context_mark and context_mark.line != mark.line:
                problem += " (%s on line %d)" % (context, context_mark.line + 1)
            return problem, mark.line
    return None, None


class Renderer(object):
    def __init__(self):
        from ansible.parsing.dataloader import DataLoader
        import ansible.template

        self.loader = DataLoader()
        self.template_module = ansible.template
        # ansible-core 2.19 replaced the templating engine and requires
        # templates to be explicitly trusted.
        self.modern = hasattr(ansible.template, "trust_as_template")

    def load_data(self, text, data_path=None):
        if not text.strip():
            return {}, None
        try:
            if self.modern:
                # Strings in vars files are templated, so trust them the way
                # DataLoader.load_from_file(trusted_as_template=True) does
                text = self.template_module.trust_as_template(text)
            # Newer ansible insists on an absolute origin for loaded data
            data =self.loader.load(text, file_name=data_path or os.path.abspath("<data>"))
        except Exception as e:
            message, line = _yaml_mark(e)
            if message is None:
                message = getattr(e, "message", None) or str(e)
            return None, _error("data", message.strip(), line)
        if data is None:
            return {}, None
        if not isinstance(data, dict):
            return None, _error(
                "data", "top level must be a mapping of variables, not %s" % type(data).__name__, 0)
        return data, None

    def template_vars(self, template_path):
        if not template_path:
            return {}
        try:
            if self.modern:
                from ansible.template import _template_vars
                return _template_vars.generate_ansible_template_vars(
                    path=template_path, fullpath=template_path, dest_path=None,
                    include_ansible_managed=True)
            from ansible.template import generate_ansible_template_vars
            return generate_ansible_template_vars(template_path, template_path, None)
        except Exception:
            return {}

    def searchpath(self, template_path):
        base = os.path.dirname(template_path) if template_path else os.getcwd()
        return [os.path.join(base, "templates"), base]

    def render(self, text, variables, template_path, trim_blocks=True, lstrip_blocks=False):
        """Render the way the ansible template action does."""
        overrides = dict(trim_blocks=trim_blocks, lstrip_blocks=lstrip_blocks)
        tm = self.template_module
        if self.modern:
            overrides["newline_sequence"] = "\n"
            templar = tm.Templar(loader=self.loader).copy_with_new_env(
                searchpath=self.searchpath(template_path), available_variables=variables)
            result = templar.template(
                tm.trust_as_template(text), escape_backslashes=False, overrides=overrides)
        else:
            templar = tm.Templar(loader=self.loader).copy_with_new_env(
                environment_class=tm.AnsibleEnvironment,
                searchpath=self.searchpath(template_path),
                newline_sequence="\n",
                available_variables=variables)
            result = templar.do_template(
                text, preserve_trailing_newlines=True, escape_backslashes=False,
                overrides=overrides)
        return "" if result is None else str(result)

    def handle(self, request):
        text = request.get("template", "")
        template_path = request.get("template_path")
        options = dict(trim_blocks=request.get("trim_blocks", True),
                       lstrip_blocks=request.get("lstrip_blocks", False))
        data, data_error = self.load_data(request.get("data", ""), request.get("data_path"))

        if data_error is not None:
            # Still surface template syntax errors alongside the data error
            errors = [data_error]
            try:
                self.render(text, {}, template_path, **options)
            except Exception as e:
                error = _template_error(e, text)
                if error["source"] == "template":
                    errors.append(error)
            return {"output": None, "errors": errors}

        variables = dict(data)
        variables.update(self.template_vars(template_path))
        try:
            return {"output": self.render(text, variables, template_path, **options),
                    "errors": []}
        except Exception as e:
            return {"output": None, "errors": [_template_error(e, text)]}


def main():
    hello = _hello()
    _send(hello)
    if "--probe" in sys.argv or hello["error"]:
        return

    renderer = Renderer()
    for line in sys.stdin:
        try:
            response = renderer.handle(json.loads(line))
        except Exception as e:
            response = {"output": None, "errors": [
                _error("render", "internal error: %s: %s" % (type(e).__name__, e))]}
        _send(response)


if __name__ == "__main__":
    main()
