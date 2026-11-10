#!/usr/bin/env python3
"""Validate TOML files, report problems with file and line, fail CI on bad TOML.

Run: python3 src/toml_validator.py config.toml
     python3 src/toml_validator.py one.toml two.toml --require name
     cat config.toml | python3 src/toml_validator.py

The tool reads one or more TOML files (or standard input) and checks each
one with the Python standard library's tomllib parser. A file that does
not parse is reported with the exact line and column of the error, plus
the offending line with a caret under the bad spot — so you can find the
mistake without opening an editor and hunting for it. Duplicate keys and
duplicate tables are parse errors in TOML, so tomllib reports them the
same way, with the line and column where the repeat happens.

With --require you can also ask for keys that must be present, and with
--require-type you can ask for keys of a given type (string, integer,
float, boolean, array, table, datetime, date, time). A file that parses
but misses a required key, or has the wrong type for one, fails too.

It is report-only and runs fully offline: it sends nothing anywhere,
needs no API key, and never changes a file.

Exit codes: 0 when every file is valid, 1 when any file has a problem,
2 for a usage or input problem (missing file, bad flag, no input at all).

Python standard library only.
"""

import argparse
import datetime
import json
import re
import sys
import tomllib
from pathlib import Path

VERSION = "1.0.0"

# Types a --require-type check can ask for, and what they map to.
TYPE_NAMES = {
    "string": str,
    "integer": int,
    "float": float,
    "boolean": bool,
    "array": list,
    "table": dict,
    "datetime": datetime.datetime,
    "date": datetime.date,
    "time": datetime.time,
}

_POSITION = re.compile(r"\(at line (\d+), column (\d+)\)")


def build_parser():
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="toml_validator",
        description=(
            "Validate TOML files. Prints VALID or INVALID per file and "
            "exits 1 on bad TOML, 2 on a usage problem."
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help="TOML file to validate. No file reads standard input.",
    )
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        metavar="KEY",
        help=(
            "A key that must be present, as a dotted path "
            "(for example --require tool.name). Repeatable."
        ),
    )
    parser.add_argument(
        "--require-type",
        action="append",
        default=[],
        metavar="KEY=TYPE",
        help=(
            "A key and the type it must have, as KEY=TYPE "
            "(for example --require-type port=integer). "
            "TYPE is one of: string, integer, float, boolean, array, "
            "table, datetime, date, time. Repeatable."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the result as JSON on standard output (summary goes to standard error).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s " + VERSION,
    )
    return parser


def split_dotted_path(path):
    """Split a dotted key path, keeping quoted parts together.

    "tool.name" -> ["tool", "name"]; '"my.key".name' -> ["my.key", "name"].
    """
    parts = []
    current = []
    in_quote = None
    for char in path:
        if in_quote is not None:
            if char == in_quote:
                in_quote = None
            else:
                current.append(char)
        elif char in ("'", '"'):
            in_quote = char
        elif char == ".":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def lookup_key(data, dotted_path):
    """Look up a dotted key path in parsed TOML data.

    Returns (found, value). A missing key and a key set to None are
    different: TOML has no null, so a found value is never None.
    """
    current = data
    for part in split_dotted_path(dotted_path):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def type_name(value):
    """The plain type name of a parsed TOML value, for error messages."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "table"
    if isinstance(value, datetime.datetime):
        return "datetime"
    if isinstance(value, datetime.date):
        return "date"
    if isinstance(value, datetime.time):
        return "time"
    return type(value).__name__


def check_required(data, required, required_types):
    """Check --require / --require-type rules against parsed TOML data.

    Returns a list of problem strings (without the INVALID prefix).
    """
    problems = []
    for key in required:
        found, _value = lookup_key(data, key)
        if not found:
            problems.append("missing required key '%s'" % key)
    for rule in required_types:
        if "=" not in rule:
            problems.append(
                "bad --require-type '%s' (use KEY=TYPE)" % rule
            )
            continue
        key, wanted = rule.split("=", 1)
        key = key.strip()
        wanted = wanted.strip()
        if wanted not in TYPE_NAMES:
            problems.append(
                "bad --require-type '%s' (unknown type '%s')"
                % (rule, wanted)
            )
            continue
        found, value = lookup_key(data, key)
        if not found:
            problems.append("missing required key '%s'" % key)
            continue
        expected = TYPE_NAMES[wanted]
        # bool is a subclass of int in Python, so check it first.
        if wanted == "integer" and isinstance(value, bool):
            problems.append(
                "key '%s' should be an integer, got boolean" % key
            )
        elif wanted == "float" and isinstance(value, bool):
            problems.append(
                "key '%s' should be a float, got boolean" % key
            )
        elif wanted == "date" and isinstance(value, datetime.datetime):
            problems.append(
                "key '%s' should be a date, got datetime" % key
            )
        elif not isinstance(value, expected):
            article = "an" if wanted[0] in "aeiou" else "a"
            problems.append(
                "key '%s' should be %s %s, got %s"
                % (key, article, wanted, type_name(value))
            )
    return problems


def validate_text(text):
    """Parse TOML text. Returns (data, error_lines).

    data is the parsed document on success, None on failure; error_lines
    is a list of report lines (without the source name) on failure.
    """
    try:
        return tomllib.loads(text), []
    except tomllib.TOMLDecodeError as error:
        message = str(error)
        match = _POSITION.search(message)
        if match:
            line_no = int(match.group(1))
            col_no = int(match.group(2))
            short = _POSITION.sub("", message).strip()
            lines = ["%d:%d: %s" % (line_no, col_no, short)]
            source_lines = text.splitlines()
            if 1 <= line_no <= len(source_lines):
                lines.append("  " + source_lines[line_no - 1])
                lines.append("  " + " " * (col_no - 1) + "^")
            return None, lines
        return None, [message]


def process_one(source, text, required, required_types):
    """Validate one input. Returns (valid, report_lines, problems).

    report_lines are the human-readable lines for this file; problems
    are machine-readable dicts with line, column and message.
    """
    data, error_lines = validate_text(text)
    if data is None:
        problems = []
        for line in error_lines:
            match = re.match(r"(\d+):(\d+): (.*)", line)
            if match:
                problems.append(
                    {
                        "line": int(match.group(1)),
                        "column": int(match.group(2)),
                        "message": match.group(3),
                    }
                )
            elif not line.startswith("  "):
                problems.append(
                    {"line": None, "column": None, "message": line}
                )
        report = ["INVALID %s:%s" % (source, error_lines[0])]
        report.extend(error_lines[1:])
        return False, report, problems
    problems = [
        {"line": None, "column": None, "message": message}
        for message in check_required(data, required, required_types)
    ]
    if problems:
        report = [
            "INVALID %s: %s" % (source, problem["message"])
            for problem in problems
        ]
        return False, report, problems
    return True, ["VALID   %s" % source], []


def read_input(path):
    """Read a file as UTF-8 text. Raises OSError / UnicodeDecodeError."""
    return Path(path).read_text(encoding="utf-8")


def run(argv=None, stdin_text=None, stdout=None, stderr=None):
    """Run the CLI. Returns the exit code. Testable without subprocess."""
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = build_parser()
    args = parser.parse_args(argv)

    for rule in args.require_type:
        if "=" not in rule:
            print(
                "error: bad --require-type '%s' (use KEY=TYPE)" % rule,
                file=stderr,
            )
            return 2
        if rule.split("=", 1)[1].strip() not in TYPE_NAMES:
            print(
                "error: bad --require-type '%s' (unknown type '%s')"
                % (rule, rule.split("=", 1)[1].strip()),
                file=stderr,
            )
            return 2

    inputs = []  # list of (source_name, text)
    if not args.files:
        if stdin_text is None:
            stdin_text = sys.stdin.read()
        inputs.append(("<stdin>", stdin_text))
    else:
        for path in args.files:
            try:
                inputs.append((path, read_input(path)))
            except FileNotFoundError:
                print("error: file not found: %s" % path, file=stderr)
                return 2
            except OSError as exc:
                print("error: cannot read %s: %s" % (path, exc), file=stderr)
                return 2
            except UnicodeDecodeError:
                print("error: %s is not valid UTF-8 text" % path, file=stderr)
                return 2

    results = []
    for source, text in inputs:
        valid, report, problems = process_one(
            source, text, args.require, args.require_type
        )
        results.append(
            {"file": source, "valid": valid, "problems": problems}
        )
        if not args.json:
            for line in report:
                print(line, file=stdout)

    checked = len(results)
    invalid = sum(1 for result in results if not result["valid"])
    if args.json:
        payload = {
            "files": results,
            "summary": {
                "checked": checked,
                "valid": checked - invalid,
                "invalid": invalid,
            },
        }
        print(json.dumps(payload, indent=2), file=stdout)
        summary = "Checked %d file(s), %d invalid." % (checked, invalid)
        print(summary, file=stderr)
    else:
        if invalid == 0:
            print("OK — %d file(s) valid." % checked, file=stdout)
        else:
            print(
                "Checked %d file(s), %d invalid." % (checked, invalid),
                file=stdout,
            )
    return 0 if invalid == 0 else 1


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
