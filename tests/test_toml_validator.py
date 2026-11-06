"""Tests for toml_validator — stdlib unittest only."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "toml_validator.py"
sys.path.insert(0, str(ROOT / "src"))

import toml_validator  # noqa: E402


def run_cli(args, stdin_text=None):
    """Run the CLI in-process and capture stdout, stderr, exit code."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = toml_validator.run(args, stdin_text=stdin_text, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


class TestValidateText(unittest.TestCase):
    def test_valid_document_parses(self):
        data, errors = toml_validator.validate_text('name = "x"\nport = 1\n')
        self.assertEqual(errors, [])
        self.assertEqual(data, {"name": "x", "port": 1})

    def test_empty_document_is_valid(self):
        data, errors = toml_validator.validate_text("")
        self.assertEqual(errors, [])
        self.assertEqual(data, {})

    def test_bad_syntax_reports_line_and_column(self):
        data, errors = toml_validator.validate_text('name = "x\n')
        self.assertIsNone(data)
        self.assertTrue(errors[0].startswith("1:"))
        self.assertIn("Illegal character", errors[0])

    def test_duplicate_key_is_an_error(self):
        data, errors = toml_validator.validate_text('name = "a"\nname = "b"\n')
        self.assertIsNone(data)
        self.assertIn("Cannot overwrite a value", errors[0])

    def test_duplicate_table_is_an_error(self):
        text = "[server]\nhost = \"a\"\n[server]\nport = 1\n"
        data, errors = toml_validator.validate_text(text)
        self.assertIsNone(data)
        self.assertIn("Cannot declare ('server',) twice", errors[0])

    def test_dotted_key_then_table_is_an_error(self):
        text = "a.b = 1\n[a.b]\nc = 2\n"
        data, errors = toml_validator.validate_text(text)
        self.assertIsNone(data)

    def test_bad_value_reports_position(self):
        data, errors = toml_validator.validate_text("port = 08\n")
        self.assertIsNone(data)
        self.assertTrue(errors[0].startswith("1:9:"))


class TestSplitDottedPath(unittest.TestCase):
    def test_plain_path(self):
        self.assertEqual(
            toml_validator.split_dotted_path("tool.name"), ["tool", "name"]
        )

    def test_quoted_part_with_dot(self):
        self.assertEqual(
            toml_validator.split_dotted_path('"my.key".name'),
            ["my.key", "name"],
        )

    def test_single_key(self):
        self.assertEqual(toml_validator.split_dotted_path("name"), ["name"])


class TestRequiredKeys(unittest.TestCase):
    def test_missing_required_key(self):
        problems = toml_validator.check_required({"name": "x"}, ["license"], [])
        self.assertEqual(problems, ["missing required key 'license'"])

    def test_present_required_key_passes(self):
        problems = toml_validator.check_required({"name": "x"}, ["name"], [])
        self.assertEqual(problems, [])

    def test_nested_required_key(self):
        data = {"server": {"port": 8080}}
        problems = toml_validator.check_required(data, ["server.port"], [])
        self.assertEqual(problems, [])
        problems = toml_validator.check_required(data, ["server.host"], [])
        self.assertEqual(problems, ["missing required key 'server.host'"])

    def test_required_type_right(self):
        data = {"port": 8080, "debug": False, "tags": ["a"]}
        problems = toml_validator.check_required(
            data,
            [],
            ["port=integer", "debug=boolean", "tags=array"],
        )
        self.assertEqual(problems, [])

    def test_required_type_wrong(self):
        data = {"port": "8080"}
        problems = toml_validator.check_required(data, [], ["port=integer"])
        self.assertEqual(
            problems, ["key 'port' should be an integer, got string"]
        )

    def test_required_type_missing_key(self):
        problems = toml_validator.check_required({}, [], ["port=integer"])
        self.assertEqual(problems, ["missing required key 'port'"])

    def test_boolean_is_not_an_integer(self):
        problems = toml_validator.check_required(
            {"debug": True}, [], ["debug=integer"]
        )
        self.assertEqual(
            problems, ["key 'debug' should be an integer, got boolean"]
        )

    def test_datetime_and_date_types(self):
        import tomllib

        data = tomllib.loads("when = 2026-01-15\nat = 2026-01-15 10:30:00\n")
        problems = toml_validator.check_required(
            data, [], ["when=date", "at=datetime"]
        )
        self.assertEqual(problems, [])

    def test_bad_require_type_rule(self):
        problems = toml_validator.check_required({}, [], ["port"])
        self.assertEqual(
            problems, ["bad --require-type 'port' (use KEY=TYPE)"]
        )

    def test_unknown_require_type(self):
        problems = toml_validator.check_required({}, [], ["port=widget"])
        self.assertEqual(
            problems,
            ["bad --require-type 'port=widget' (unknown type 'widget')"],
        )


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_valid_file_exits_zero(self):
        path = self.write("good.toml", 'name = "x"\n')
        code, out, _err = run_cli([path])
        self.assertEqual(code, 0)
        self.assertIn("VALID   %s" % path, out)
        self.assertIn("OK — 1 file(s) valid.", out)

    def test_bad_file_exits_one_with_line_col(self):
        path = self.write("bad.toml", 'name = "x\n')
        code, out, _err = run_cli([path])
        self.assertEqual(code, 1)
        self.assertIn("INVALID %s:1:" % path, out)
        self.assertIn("^", out)

    def test_duplicate_key_file_exits_one(self):
        path = self.write("dup.toml", 'name = "a"\nname = "b"\n')
        code, out, _err = run_cli([path])
        self.assertEqual(code, 1)
        self.assertIn("Cannot overwrite a value", out)

    def test_duplicate_table_file_exits_one(self):
        path = self.write(
            "dup.toml", "[server]\nhost = \"a\"\n[server]\nport = 1\n"
        )
        code, out, _err = run_cli([path])
        self.assertEqual(code, 1)
        self.assertIn("Cannot declare ('server',) twice", out)

    def test_multiple_files_mixed(self):
        good = self.write("good.toml", 'name = "x"\n')
        bad = self.write("bad.toml", 'name = "x\n')
        code, out, _err = run_cli([good, bad])
        self.assertEqual(code, 1)
        self.assertIn("VALID   %s" % good, out)
        self.assertIn("INVALID %s" % bad, out)
        self.assertIn("Checked 2 file(s), 1 invalid.", out)

    def test_stdin_valid(self):
        code, out, _err = run_cli([], stdin_text='name = "x"\n')
        self.assertEqual(code, 0)
        self.assertIn("VALID   <stdin>", out)

    def test_stdin_invalid(self):
        code, out, _err = run_cli([], stdin_text='name = "x\n')
        self.assertEqual(code, 1)
        self.assertIn("INVALID <stdin>:1:", out)

    def test_require_missing_exits_one(self):
        path = self.write("good.toml", 'name = "x"\n')
        code, out, _err = run_cli([path, "--require", "license"])
        self.assertEqual(code, 1)
        self.assertIn("missing required key 'license'", out)

    def test_require_present_exits_zero(self):
        path = self.write("good.toml", 'name = "x"\n')
        code, out, _err = run_cli([path, "--require", "name"])
        self.assertEqual(code, 0)

    def test_require_type_wrong_exits_one(self):
        path = self.write("good.toml", 'port = "8080"\n')
        code, out, _err = run_cli([path, "--require-type", "port=integer"])
        self.assertEqual(code, 1)
        self.assertIn("should be an integer, got string", out)

    def test_bad_require_type_flag_exits_two(self):
        path = self.write("good.toml", 'name = "x"\n')
        code, _out, err = run_cli([path, "--require-type", "port"])
        self.assertEqual(code, 2)
        self.assertIn("bad --require-type", err)

    def test_unknown_require_type_exits_two(self):
        path = self.write("good.toml", 'name = "x"\n')
        code, _out, err = run_cli([path, "--require-type", "port=widget"])
        self.assertEqual(code, 2)
        self.assertIn("unknown type 'widget'", err)

    def test_missing_file_exits_two(self):
        code, _out, err = run_cli([str(self.dir / "nope.toml")])
        self.assertEqual(code, 2)
        self.assertIn("file not found", err)

    def test_json_output_parses(self):
        good = self.write("good.toml", 'name = "x"\n')
        bad = self.write("bad.toml", 'name = "x\n')
        code, out, err = run_cli([good, bad, "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload["summary"], {"checked": 2, "valid": 1, "invalid": 1})
        self.assertTrue(payload["files"][0]["valid"])
        self.assertFalse(payload["files"][1]["valid"])
        self.assertEqual(payload["files"][1]["problems"][0]["line"], 1)
        self.assertIn("Checked 2 file(s), 1 invalid.", err)

    def test_json_pass_summary_on_stderr(self):
        path = self.write("good.toml", 'name = "x"\n')
        code, out, err = run_cli([path, "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["summary"]["invalid"], 0)
        self.assertIn("Checked 1 file(s), 0 invalid.", err)

    def test_version_flag(self):
        with self.assertRaises(SystemExit) as caught:
            run_cli(["--version"])
        self.assertEqual(caught.exception.code, 0)

    def test_input_files_unchanged(self):
        text = 'name = "x"\n'
        path = self.write("good.toml", text)
        run_cli([path])
        run_cli([path, "--require", "license"])
        self.assertEqual(Path(path).read_text(encoding="utf-8"), text)


class TestBundledExamples(unittest.TestCase):
    def test_sample_output_matches_fresh_run(self):
        expected = (ROOT / "examples" / "sample-output.txt").read_text(
            encoding="utf-8"
        )
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, expected)

    def test_readme_quotes_real_output(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        sample = (ROOT / "examples" / "sample-output.txt").read_text(
            encoding="utf-8"
        )
        for line in [
            "VALID   examples/valid.toml",
            "INVALID examples/invalid-syntax.toml:2:21: Illegal character '\\n'",
            "INVALID examples/duplicate-key.toml:4:16: Cannot overwrite a value",
            "INVALID examples/duplicate-table.toml:5:8: Cannot declare ('server',) twice",
            "INVALID examples/valid.toml: missing required key 'license'",
        ]:
            self.assertIn(line, readme, "README must quote: %s" % line)
            self.assertIn(line, sample, "sample output must contain: %s" % line)

    def test_run_example_script_exits_zero(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)


class TestHygiene(unittest.TestCase):
    def test_no_placeholder_text(self):
        banned = ["TODO", "FIXME", "coming soon", "lorem", "API_KEY"]
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for word in banned:
                if word in text:
                    hits.append("%s: %s" % (path, word))
        self.assertEqual(hits, [])

    def test_no_absolute_workspace_paths(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "/home/" in text or "/Users/" in text or "C:\\" in text:
                hits.append(str(path))
        self.assertEqual(hits, [])

    def test_stdlib_only(self):
        import ast

        allowed = set(sys.stdlib_module_names) | {"toml_validator"}
        source = (ROOT / "src" / "toml_validator.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])
        self.assertEqual(imported - allowed, set())

    def test_gitignore_lists_env_first(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], ".env")


if __name__ == "__main__":
    unittest.main()
