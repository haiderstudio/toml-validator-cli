#!/bin/sh
# Run the validator on the bundled examples.
# Run from the repo root: sh examples/run-example.sh
# The bad-files run exits 1 because three example files are bad on
# purpose — that is the expected result here.
set -e
cd "$(dirname "$0")/.."
echo "--- valid file ---"
python3 src/toml_validator.py examples/valid.toml
echo "--- bad files ---"
python3 src/toml_validator.py examples/invalid-syntax.toml examples/duplicate-key.toml examples/duplicate-table.toml || true
echo "--- required key ---"
python3 src/toml_validator.py examples/valid.toml --require license || true
