"""#523: scripts/build_voice_shortcuts.py builds the two Siri Shortcuts.

The files mirror Help → Hands-free voice review steps 1-18 action for
action, carry NO token (an import question asks for it when the Shortcut
is added), and every variable points at a real earlier action. Signing
needs macOS's `shortcuts` tool, so main() is tested with it stubbed.
"""

from __future__ import annotations

import importlib.util
import plistlib
import subprocess

import pytest

_spec = importlib.util.spec_from_file_location(
    "build_voice_shortcuts", "scripts/build_voice_shortcuts.py"
)
bvs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bvs)

PROD = "https://web-production-3e3ae.up.railway.app"
OBJ = "￼"


def _ids(workflow):
    return [
        a["WFWorkflowActionIdentifier"].removeprefix("is.workflow.actions.")
        for a in workflow["WFWorkflowActions"]
    ]


def _params(workflow, ident):
    return [
        a["WFWorkflowActionParameters"]
        for a in workflow["WFWorkflowActions"]
        if a["WFWorkflowActionIdentifier"] == f"is.workflow.actions.{ident}"
    ]


@pytest.fixture(scope="module")
def built():
    return bvs.build(PROD)


def test_builds_the_two_shortcuts_the_help_names(built):
    assert list(built) == ["Review my tasks", "Add a task"]


def test_review_follows_help_steps(built):
    assert _ids(built["Review my tasks"]) == [
        "gettext",
        "setvariable",  # 2-3 token
        "downloadurl",
        "getvalueforkey",  # 4-6 queue → items
        "repeat.each",  # 7
        "getvalueforkey",
        "speaktext",  # 8-9 title
        "getvalueforkey",
        "setvariable",  # 11-12 TaskId
        "dictatetext",
        "downloadurl",  # 13-14 answer
        "getvalueforkey",
        "speaktext",  # 15-16 say
        "repeat.each",  # End Repeat
    ]


def test_add_a_task_follows_help_steps(built):
    assert _ids(built["Add a task"]) == [
        "gettext",
        "setvariable",
        "speaktext",
        "dictatetext",
        "downloadurl",
        "getvalueforkey",
        "speaktext",
    ]


@pytest.mark.parametrize("name", ["Review my tasks", "Add a task"])
def test_no_token_in_the_file(built, name):
    workflow = built[name]
    first = workflow["WFWorkflowActions"][0]
    assert first["WFWorkflowActionIdentifier"] == "is.workflow.actions.gettext"
    assert first["WFWorkflowActionParameters"]["WFTextActionText"] == ""
    (question,) = workflow["WFWorkflowImportQuestions"]
    assert question["ActionIndex"] == 0
    assert question["ParameterKey"] == "WFTextActionText"
    assert "Copy header value" in question["Text"]
    assert b"Bearer ey" not in plistlib.dumps(workflow)
    assert _params(workflow, "setvariable")[0]["WFVariableName"] == "Token"


@pytest.mark.parametrize("name", ["Review my tasks", "Add a task"])
def test_every_request_sends_the_token(built, name):
    for params in _params(built[name], "downloadurl"):
        (header,) = params["WFHTTPHeaders"]["Value"]["WFDictionaryFieldValueItems"]
        assert header["WFKey"]["Value"]["string"] == "Authorization"
        value = header["WFValue"]["Value"]
        assert value["string"] == OBJ
        assert value["attachmentsByRange"] == {
            "{0, 1}": {"Type": "Variable", "VariableName": "Token"}
        }


def test_review_urls_methods_and_body(built):
    queue, answer = _params(built["Review my tasks"], "downloadurl")
    assert queue["WFURL"]["Value"]["string"] == f"{PROD}/api/voice-review/queue"
    assert queue["WFHTTPMethod"] == "GET"
    assert "WFJSONValues" not in queue

    url = answer["WFURL"]["Value"]
    assert url["string"] == f"{PROD}/api/voice-review/{OBJ}/answer"
    offset = len(f"{PROD}/api/voice-review/")
    assert url["attachmentsByRange"] == {
        f"{{{offset}, 1}}": {"Type": "Variable", "VariableName": "TaskId"}
    }
    assert answer["WFHTTPMethod"] == "POST"
    assert answer["WFHTTPBodyType"] == "JSON"
    (field,) = answer["WFJSONValues"]["Value"]["WFDictionaryFieldValueItems"]
    assert field["WFKey"]["Value"]["string"] == "text"
    ref = field["WFValue"]["Value"]["attachmentsByRange"]["{0, 1}"]
    assert ref["OutputName"] == "Dictated Text"


def test_add_a_task_posts_to_tasks(built):
    (create,) = _params(built["Add a task"], "downloadurl")
    assert create["WFURL"]["Value"]["string"] == f"{PROD}/api/voice-review/tasks"
    assert create["WFHTTPMethod"] == "POST"
    assert (
        _params(built["Add a task"], "speaktext")[0]["WFText"]["Value"]["string"]
        == "What's the task?"
    )


def test_dictionary_keys(built):
    keys = [p["WFDictionaryKey"] for p in _params(built["Review my tasks"], "getvalueforkey")]
    assert keys == ["items", "title", "id", "say"]
    assert [p["WFDictionaryKey"] for p in _params(built["Add a task"], "getvalueforkey")] == ["say"]


@pytest.mark.parametrize("name", ["Review my tasks", "Add a task"])
def test_every_output_reference_points_back(built, name):
    """A pill must name an action ABOVE it, with that action's output."""
    output_names = {
        "gettext": "Text",
        "downloadurl": "Contents of URL",
        "getvalueforkey": "Dictionary Value",
        "dictatetext": "Dictated Text",
    }
    seen: dict[str, str] = {}
    refs = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("Type") == "ActionOutput":
                refs.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for action in built[name]["WFWorkflowActions"]:
        refs.clear()
        walk(action["WFWorkflowActionParameters"])
        for ref in refs:
            assert seen.get(ref["OutputUUID"]) == ref["OutputName"], ref
        ident = action["WFWorkflowActionIdentifier"].removeprefix("is.workflow.actions.")
        uid = action["WFWorkflowActionParameters"].get("UUID")
        if uid and ident in output_names:
            seen[uid] = output_names[ident]


def test_repeat_block_opens_and_closes(built):
    start, end = _params(built["Review my tasks"], "repeat.each")
    assert (start["WFControlFlowMode"], end["WFControlFlowMode"]) == (0, 2)
    assert start["GroupingIdentifier"] == end["GroupingIdentifier"]
    assert start["WFInput"]["Value"]["OutputName"] == "Dictionary Value"


def test_inner_lookups_read_the_repeat_item(built):
    _, title, task_id, _ = _params(built["Review my tasks"], "getvalueforkey")
    for params in (title, task_id):
        assert params["WFInput"]["Value"] == {"Type": "Variable", "VariableName": "Repeat Item"}


def test_base_url_option(built):
    local = bvs.build("http://localhost:5111/")
    (create,) = _params(local["Add a task"], "downloadurl")
    assert create["WFURL"]["Value"]["string"] == "http://localhost:5111/api/voice-review/tasks"


def test_main_without_the_shortcuts_tool_says_why(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(bvs.shutil, "which", lambda _: None)
    assert bvs.main(["--out", str(tmp_path)]) == 2
    assert "macOS" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_main_signs_each_file(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(cmd, check, capture_output, text):
        calls.append(cmd)
        out = cmd[cmd.index("--output") + 1]
        with open(out, "wb") as f:
            f.write(b"signed")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bvs.shutil, "which", lambda _: "/usr/bin/shortcuts")
    monkeypatch.setattr(bvs.subprocess, "run", fake_run)
    assert bvs.main(["--out", str(tmp_path)]) == 0
    assert [c[:4] for c in calls] == [["shortcuts", "sign", "--mode", "anyone"]] * 2
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "Add a task.shortcut",
        "Review my tasks.shortcut",
    ]
    assert "Review my tasks.shortcut" in capsys.readouterr().out


def test_main_reports_a_failed_signing(monkeypatch, tmp_path, capsys):
    def failing_run(cmd, check, capture_output, text):
        raise subprocess.CalledProcessError(1, cmd, "", "not signed in to iCloud")

    monkeypatch.setattr(bvs.shutil, "which", lambda _: "/usr/bin/shortcuts")
    monkeypatch.setattr(bvs.subprocess, "run", failing_run)
    assert bvs.main(["--out", str(tmp_path)]) == 1
    assert "not signed in to iCloud" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_help_gives_the_command(authed_client):
    """Help → Hands-free voice review names this script, the way to add the
    files, and the tests to run after (steps 10, 17 and 21)."""
    page = authed_client.get("/docs").get_data(as_text=True)
    start = page.index('<section id="voice-review-shortcut"')
    section = page[start : page.index("</section>", start)]
    assert "python3 scripts/build_voice_shortcuts.py --open" in section
    assert "Add Shortcut" in section
    assert "Copy header value" in section
    assert "steps 10, 17 and 21" in section
