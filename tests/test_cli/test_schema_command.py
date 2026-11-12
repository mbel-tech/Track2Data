"""`track2data schema`: the JSON Schema for .t2d.json project files.

Editors (VS Code, PyCharm) use the schema to autocomplete and check a project file while
someone edits it by hand. The committed copy in schemas/ must match the model, or editors
would flag valid files or miss real mistakes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from track2data.cli import cli
from track2data.core.manifest import json_schema

REPO = Path(__file__).resolve().parents[2]
COMMITTED = REPO / "schemas" / "project.t2d.schema.json"
EXAMPLE = REPO / "examples" / "example.t2d.json"


def test_schema_is_a_2020_12_schema_for_the_manifest() -> None:
    schema = json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert {"project_name", "sessions", "zones", "metrics"} <= set(schema["properties"])


def test_cli_prints_the_schema() -> None:
    result = CliRunner().invoke(cli, ["schema"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == json_schema()


def test_cli_writes_the_schema_to_a_file(tmp_path: Path) -> None:
    out = tmp_path / "s.json"
    result = CliRunner().invoke(cli, ["schema", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text(encoding="utf-8")) == json_schema()


def test_committed_schema_matches_the_model() -> None:
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert committed == json_schema(), (
        "schemas/project.t2d.schema.json is stale; regenerate it with "
        "`track2data schema --out schemas/project.t2d.schema.json`"
    )


def test_example_project_validates_against_the_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    jsonschema.validate(example, json_schema())


def test_schema_rejects_a_wrong_type() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    bad = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    bad["sessions"] = "not a list"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, json_schema())
