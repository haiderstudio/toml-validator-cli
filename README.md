# toml-validator-cli

Validate TOML files, fail CI on bad TOML.

[![CI](https://github.com/haiderstudio/toml-validator-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/toml-validator-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`toml_validator` reads one or more TOML files (or standard input) and
checks each one with Python's standard-library `tomllib` parser. A file
that does not parse is reported with the exact line and column of the
error, plus the offending line with a caret under the bad spot — so you
can find the mistake without opening an editor and hunting for it.

- Duplicate keys and duplicate tables are parse errors in TOML, so
  they are reported the same way, with the line and column where the
  repeat happens. The first error is reported; fix it and run again
  to see the next one.
- `--require KEY` asks for a key that must be present, as a dotted
  path (`--require server.host`). A file that parses but misses a
  required key fails.
- `--require-type KEY=TYPE` asks for a key of a given type: string,
  integer, float, boolean, array, table, datetime, date, or time.
  A file that parses but has the wrong type for a key fails.
- `--json` prints the result as machine-readable JSON (the summary
  line goes to standard error, so standard output stays clean JSON).
- It exits 1 when any file has a problem, so it can fail a CI run,
  and 0 when every file is valid.
- It is report-only and runs fully offline: it sends nothing anywhere,
  needs no API key, and never changes a file.

## What it does NOT do

- It does not convert TOML to anything else, and it does not fix or
  rewrite a bad file. A missing quote is reported, not repaired.
- It does not check a TOML file against a full schema. `--require`
  and `--require-type` cover one key at a time; a deep shape check
  is a different tool's job.
- It does not check TOML inside other files (a TOML block inside a
  Markdown file, for example). It reads TOML files only.
- It does not fetch files from the network. Every input is a local
  file or standard input.

## Who it is for

Anyone who keeps TOML files around and wants a quick, scriptable
check that they are well-formed: a developer adding a CI step that
fails the build on a broken `pyproject.toml` or config file, someone
hand-editing a settings file, or anyone piping TOML through a
validator before committing it. If the file is valid, you get a
plain VALID line; if it is not, the report says exactly which line
and column broke.

## How this differs from similar tools

TOML validators already exist, but none of them is this exact tool.
The exact name `toml-validator-cli` matches 0 repositories on
GitHub. The closest same-named repo, staticdev/toml-validator
(4 stars, Python), is archived and was last pushed in 2021. The
dedicated command-line validators are Go tools that need a Go
install: martinlindhe/validtoml validates TOML syntax, and
BurntSushi/toml's `tomlv` reports only one error at a time. The
bigger names in the wider field are libraries, not CLIs:
xoofx/Tomlyn (605 stars) is a .NET parser and validator library,
msgspec (4.2k stars) is a Python serialization library for many
formats, and abravalheri/validate-pyproject (210 stars) checks
`pyproject.toml` only. Boeing's config-file-validator (518 stars)
validates 18 config file types from a Go binary — a broad toolchain,
not a TOML-only check. The one that checks `pyproject.toml` against
a schema is a different job from checking that any TOML file parses.

This tool does a narrower job: a Python standard-library-only CLI
that validates any TOML file, reports every error with a line, a
column, and a caret, checks required keys and types when you ask,
and exits 1 on bad TOML for CI — no install beyond Python, no Go
binary, no schema, no network.

## Install

Python standard library only — no packages to download. You need
Python 3.11 or newer, because `tomllib` ships with Python 3.11.
Clone the repo and run it in place:

```sh
git clone https://github.com/haiderstudio/toml-validator-cli.git
cd toml-validator-cli
python3 src/toml_validator.py examples/valid.toml
```

```text
VALID   examples/valid.toml
OK — 1 file(s) valid.
```

## Usage

Check one file:

```sh
python3 src/toml_validator.py examples/valid.toml
```

Check several files at once:

```sh
python3 src/toml_validator.py examples/valid.toml examples/duplicate-key.toml
```

```text
VALID   examples/valid.toml
INVALID examples/duplicate-key.toml:4:16: Cannot overwrite a value
  name = "second"
                 ^
Checked 2 file(s), 1 invalid.
```

Check a file from standard input (no file named reads stdin):

```sh
cat examples/valid.toml | python3 src/toml_validator.py
```

Ask for a key that must be there:

```sh
python3 src/toml_validator.py examples/valid.toml --require license
```

```text
INVALID examples/valid.toml: missing required key 'license'
Checked 1 file(s), 1 invalid.
```

Ask for a key of a given type (a dotted path works here too):

```sh
python3 src/toml_validator.py examples/valid.toml --require-type server.port=integer --require name
```

```text
VALID   examples/valid.toml
OK — 1 file(s) valid.
```

A wrong type fails with the type it found:

```sh
python3 src/toml_validator.py examples/valid.toml --require-type name=integer
```

```text
INVALID examples/valid.toml: key 'name' should be an integer, got string
Checked 1 file(s), 1 invalid.
```

Machine-readable output with `--json` (the summary goes to
standard error, so standard output is clean JSON):

```sh
python3 src/toml_validator.py examples/valid.toml examples/duplicate-key.toml --json
```

```json
{
  "files": [
    {
      "file": "examples/valid.toml",
      "valid": true,
      "problems": []
    },
    {
      "file": "examples/duplicate-key.toml",
      "valid": false,
      "problems": [
        {
          "line": 4,
          "column": 16,
          "message": "Cannot overwrite a value"
        }
      ]
    }
  ],
  "summary": {
    "checked": 2,
    "valid": 1,
    "invalid": 1
  }
}
```

Exit codes: 0 when every file is valid, 1 when any file has a
problem, 2 for a usage or input problem (a missing file, a bad
`--require-type`, no input at all).

## Examples

### 1. A bad file — syntax error

`examples/invalid-syntax.toml` has a string that is never closed:

```sh
python3 src/toml_validator.py examples/invalid-syntax.toml
```

```text
INVALID examples/invalid-syntax.toml:2:21: Illegal character '\n'
  name = "example-site
                      ^
Checked 1 file(s), 1 invalid.
```

### 2. A bad file — duplicate table

`examples/duplicate-table.toml` declares `[server]` twice:

```sh
python3 src/toml_validator.py examples/duplicate-table.toml
```

```text
INVALID examples/duplicate-table.toml:5:8: Cannot declare ('server',) twice
  [server]
         ^
Checked 1 file(s), 1 invalid.
```

### 3. The bundled examples, all at once

```sh
sh examples/run-example.sh
```

The script checks the valid file (passes), then the three bad
files (all fail, on purpose), then asks for a key the valid file
does not have. Its full output is in
`examples/sample-output.txt`. The bad-files run exits 1, which is
the expected result — the script ends with exit 0 so it can be run
as a demo.

## How it is tested

44 tests, standard library `unittest` only, no packages to install:

```sh
python3 tests/test_toml_validator.py
```

The tests cover: valid and empty documents, bad syntax with a
line and column, duplicate keys, duplicate tables, dotted keys,
required keys (present, missing, nested, quoted parts), required
types (right, wrong, boolean-is-not-an-integer, datetime and date),
bad `--require-type` flags, stdin, missing files, `--json` output,
`--version`, input files left unchanged, the bundled examples
(sample output compared byte-for-byte against a fresh run, and the
README-quoted outputs checked against it), and hygiene checks
(no placeholder text, no absolute paths, stdlib imports only,
`.env` first in `.gitignore`).

## Contributing

Small, focused improvements are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The idea of
validating TOML files is not new — the similar tools named above
(martinlindhe/validtoml, BurntSushi/toml's `tomlv`,
staticdev/toml-validator, Boeing's config-file-validator) are
listed in "How this differs" — but every line of code here is
original, and the tool builds on nothing but Python's standard
library `tomllib` parser.
