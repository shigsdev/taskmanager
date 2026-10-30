"""Build the two Siri voice-review Shortcuts as signed files (#523).

Help → Hands-free voice review builds "Review my tasks" and "Add a task" by
hand, action by action (steps 1-18). On a Mac this script writes the same
two Shortcuts as files and signs them with macOS's ``shortcuts`` tool;
opening each file shows Shortcuts' Add Shortcut window.

The files carry NO token. Each Shortcut's first action is an empty Text
action, and an import question asks for the token when the Shortcut is
added: paste the value from Settings → Siri voice review → Copy header
value (``Bearer …``). So nothing secret is ever written to disk here.

Usage (macOS, in the taskmanager folder; needs only Python's stdlib)::

    python3 scripts/build_voice_shortcuts.py --open

``--out`` picks the folder (default ``./voice-shortcuts``), ``--base-url``
another deploy (default production).
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

DEFAULT_BASE_URL = "https://web-production-3e3ae.up.railway.app"
OBJ = "￼"  # the character a variable pill occupies in a text field
_IMPORT_PROMPT = (
    "Paste your Task Manager voice token: Settings → Siri voice review → "
    'Copy header value (it starts with "Bearer ").'
)


def _uid() -> str:
    return str(uuid.uuid4()).upper()


def _out(action_uuid: str, name: str) -> dict:
    return {"Type": "ActionOutput", "OutputUUID": action_uuid, "OutputName": name}


def _var(name: str) -> dict:
    return {"Type": "Variable", "VariableName": name}


def _attachment(ref: dict) -> dict:
    return {"Value": ref, "WFSerializationType": "WFTextTokenAttachment"}


def _text(before: str, ref: dict | None = None, after: str = "") -> dict:
    """A text field: plain text, optionally with one variable pill in it.
    Shortcuts counts the pill's position in UTF-16 units."""
    if ref is None:
        return {"Value": {"string": before}, "WFSerializationType": "WFTextTokenString"}
    at = len(before.encode("utf-16-le")) // 2
    return {
        "Value": {"string": before + OBJ + after, "attachmentsByRange": {f"{{{at}, 1}}": ref}},
        "WFSerializationType": "WFTextTokenString",
    }


def _fields(*pairs: tuple[str, dict]) -> dict:
    return {
        "Value": {
            "WFDictionaryFieldValueItems": [
                {"WFItemType": 0, "WFKey": _text(key), "WFValue": value} for key, value in pairs
            ]
        },
        "WFSerializationType": "WFDictionaryFieldValue",
    }


def _action(ident: str, **params) -> dict:
    return {
        "WFWorkflowActionIdentifier": f"is.workflow.actions.{ident}",
        "WFWorkflowActionParameters": params,
    }


def _token_actions() -> list[dict]:
    text_uuid = _uid()
    return [
        _action("gettext", UUID=text_uuid, WFTextActionText=""),
        _action(
            "setvariable", WFVariableName="Token", WFInput=_attachment(_out(text_uuid, "Text"))
        ),
    ]


def _request(action_uuid: str, url: dict, method: str, body_ref: dict | None = None) -> dict:
    params = {
        "UUID": action_uuid,
        "WFURL": url,
        "WFHTTPMethod": method,
        "ShowHeaders": True,
        "WFHTTPHeaders": _fields(("Authorization", _text("", _var("Token")))),
    }
    if body_ref is not None:
        params["WFHTTPBodyType"] = "JSON"
        params["WFJSONValues"] = _fields(("text", _text("", body_ref)))
    return _action("downloadurl", **params)


def _get_value(action_uuid: str, key: str, source: dict) -> dict:
    return _action(
        "getvalueforkey",
        UUID=action_uuid,
        WFDictionaryKey=key,
        WFGetDictionaryValueType="Value",
        WFInput=_attachment(source),
    )


def _speak_value(source_uuid: str) -> dict:
    return _action("speaktext", WFText=_text("", _out(source_uuid, "Dictionary Value")))


def _review_my_tasks(api: str) -> list[dict]:
    queue, items, title, task_id, dictated, answer, say = (_uid() for _ in range(7))
    group = _uid()
    return [
        *_token_actions(),  # steps 2-3
        _request(queue, _text(f"{api}/queue"), "GET"),  # 4-5
        _get_value(items, "items", _out(queue, "Contents of URL")),  # 6
        _action(  # 7
            "repeat.each",
            UUID=_uid(),
            GroupingIdentifier=group,
            WFControlFlowMode=0,
            WFInput=_attachment(_out(items, "Dictionary Value")),
        ),
        _get_value(title, "title", _var("Repeat Item")),  # 8
        _speak_value(title),  # 9
        _get_value(task_id, "id", _var("Repeat Item")),  # 11
        _action(  # 12
            "setvariable",
            WFVariableName="TaskId",
            WFInput=_attachment(_out(task_id, "Dictionary Value")),
        ),
        _action("dictatetext", UUID=dictated),  # 13
        _request(  # 14
            answer,
            _text(f"{api}/", _var("TaskId"), "/answer"),
            "POST",
            body_ref=_out(dictated, "Dictated Text"),
        ),
        _get_value(say, "say", _out(answer, "Contents of URL")),  # 15
        _speak_value(say),  # 16
        _action("repeat.each", UUID=_uid(), GroupingIdentifier=group, WFControlFlowMode=2),
    ]


def _add_a_task(api: str) -> list[dict]:
    dictated, created, say = _uid(), _uid(), _uid()
    return [
        *_token_actions(),
        _action("speaktext", WFText=_text("What's the task?")),
        _action("dictatetext", UUID=dictated),
        _request(created, _text(f"{api}/tasks"), "POST", body_ref=_out(dictated, "Dictated Text")),
        _get_value(say, "say", _out(created, "Contents of URL")),
        _speak_value(say),
    ]


def _workflow(actions: list[dict], glyph: int) -> dict:
    return {
        "WFWorkflowActions": actions,
        "WFWorkflowClientVersion": "2700",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": 4282601983,
            "WFWorkflowIconGlyphNumber": glyph,
        },
        "WFWorkflowImportQuestions": [
            {
                "ActionIndex": 0,
                "Category": "Parameter",
                "ParameterKey": "WFTextActionText",
                "DefaultValue": "",
                "Text": _IMPORT_PROMPT,
            }
        ],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowTypes": [],
        "WFWorkflowHasShortcutInputVariables": False,
        "WFQuickActionSurfaces": [],
    }


def build(base_url: str = DEFAULT_BASE_URL) -> dict[str, dict]:
    """The two Shortcuts by name, as Shortcuts workflow dicts."""
    api = base_url.rstrip("/") + "/api/voice-review"
    return {
        "Review my tasks": _workflow(_review_my_tasks(api), 59511),
        "Add a task": _workflow(_add_a_task(api), 59446),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Siri voice-review Shortcuts (macOS).")
    parser.add_argument("--out", default="voice-shortcuts", help="Folder for the .shortcut files.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="The app's address.")
    parser.add_argument(
        "--open", action="store_true", help="Open each file to add it to Shortcuts."
    )
    args = parser.parse_args(argv)

    if shutil.which("shortcuts") is None:
        print(
            "ERROR: macOS's `shortcuts` tool isn't here. Run this on a Mac (macOS 12 or later), "
            "or build the Shortcuts by hand: Help → Hands-free voice review.",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, workflow in build(args.base_url).items():
            unsigned = Path(tmp) / f"{name}.shortcut"
            unsigned.write_bytes(plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY))
            signed = out_dir / f"{name}.shortcut"
            try:
                subprocess.run(
                    [
                        "shortcuts",
                        "sign",
                        "--mode",
                        "anyone",
                        "--input",
                        str(unsigned),
                        "--output",
                        str(signed),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"ERROR: signing {name} failed: {(e.stderr or '').strip()}", file=sys.stderr)
                for path in written:
                    path.unlink(missing_ok=True)
                return 1
            written.append(signed)

    for path in written:
        print(path)
        if args.open:
            subprocess.run(["open", str(path)], check=False)
    print(
        "Open each file, paste your token (Settings → Siri voice review → Copy header value) "
        "and click Add Shortcut.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
