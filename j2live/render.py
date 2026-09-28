"""Template rendering with structured error reporting.

Kept free of GTK so it can be exercised directly.
"""
import enum
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional

import jinja2
import ruamel.yaml
from ruamel.yaml.error import MarkedYAMLError

from j2live.util import template_from_string

_yaml = ruamel.yaml.YAML(typ='rt')

# Filename jinja2 assigns to frames of templates compiled with from_string
_TEMPLATE_FILENAME = "<template>"


class ErrorSource(enum.Enum):
    DATA = "data"
    TEMPLATE = "template"
    RENDER = "render"


@dataclass
class RenderError:
    source: ErrorSource
    message: str
    # Zero-based line in the offending buffer, if known
    line: Optional[int] = None

    def describe(self) -> str:
        where = {
            ErrorSource.DATA: "Data",
            ErrorSource.TEMPLATE: "Template syntax",
            ErrorSource.RENDER: "Render",
        }[self.source]
        if self.line is not None:
            where += f" error on line {self.line + 1}"
        else:
            where += " error"
        return f"{where}: {self.message}"

    @classmethod
    def from_json(cls, obj: dict) -> "RenderError":
        return cls(ErrorSource(obj["source"]), obj["message"], obj.get("line"))


@dataclass
class RenderOptions:
    """Whitespace options of the ansible template module, with its defaults"""
    trim_blocks: bool = True
    lstrip_blocks: bool = False


@dataclass
class RenderResult:
    output: Optional[str] = None
    errors: list[RenderError] = field(default_factory=list)


def parse_data(text: str) -> tuple[Optional[dict], Optional[RenderError]]:
    """Parse YAML data into a mapping suitable for rendering."""
    try:
        data = _yaml.load(text)
    except MarkedYAMLError as e:
        mark = e.problem_mark or e.context_mark
        message = e.problem or e.context or str(e)
        # e.g. an unclosed flow sequence fails where parsing stopped, but the
        # useful hint is where it was opened
        if (e.problem and e.context and e.context_mark and mark
                and e.context_mark.line != mark.line):
            message += f" ({e.context} on line {e.context_mark.line + 1})"
        return None, RenderError(ErrorSource.DATA, message,
                                 mark.line if mark else None)
    except Exception as e:
        return None, RenderError(ErrorSource.DATA, str(e))

    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, RenderError(
            ErrorSource.DATA,
            f"top level must be a mapping of variables, not {type(data).__name__}",
            0)
    return data, None


def parse_template(text: str, options: RenderOptions = RenderOptions()
                   ) -> tuple[Optional[jinja2.Template], Optional[RenderError]]:
    try:
        return template_from_string(text, trim_blocks=options.trim_blocks,
                                    lstrip_blocks=options.lstrip_blocks), None
    except jinja2.TemplateSyntaxError as e:
        return None, RenderError(ErrorSource.TEMPLATE, e.message or str(e),
                                 e.lineno - 1 if e.lineno else None)
    except Exception as e:
        return None, RenderError(ErrorSource.TEMPLATE, str(e))


def _template_line(exc: BaseException) -> Optional[int]:
    """Find the innermost template line in an exception's traceback."""
    line = None
    for frame in traceback.extract_tb(exc.__traceback__):
        if frame.filename == _TEMPLATE_FILENAME and frame.lineno:
            line = frame.lineno - 1
    return line


def render(template: jinja2.Template, data: dict[str, Any]) -> RenderResult:
    try:
        return RenderResult(output=template.render(**data))
    except Exception as e:
        message = str(e) or type(e).__name__
        if not isinstance(e, jinja2.TemplateError):
            message = f"{type(e).__name__}: {message}"
        return RenderResult(errors=[RenderError(ErrorSource.RENDER, message,
                                                _template_line(e))])


def render_plain(template_text: str, data_text: str,
                 options: RenderOptions = RenderOptions()) -> RenderResult:
    """Render with stock Jinja2 and ruamel YAML, without Ansible."""
    errors = []
    data, data_error = parse_data(data_text)
    if data_error:
        errors.append(data_error)
    template, template_error = parse_template(template_text, options)
    if template_error:
        errors.append(template_error)
    if errors:
        return RenderResult(errors=errors)
    return render(template, data)
