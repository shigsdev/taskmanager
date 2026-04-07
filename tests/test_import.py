"""Integration tests for import feature (Step 17).

Two import flows:
1. OneNote text → parse into task candidates → review → create in Inbox
2. Excel .xlsx → parse into goal candidates → review → create goals

Key testing concepts:
- **Text parsing** — bullet/numbered/checkbox detection, header skipping
- **Excel parsing** — column mapping, enum validation, malformed handling
- **Duplicate detection** — existing tasks/goals flagged before import
- **ImportLog** — audit trail entry created on every import
"""
from __future__ import annotations

import io

import pytest

import auth
from models import Goal, GoalCategory, GoalPriority, ImportLog, Task, TaskType, Tier, db

# --- Helper: create Excel bytes in memory ------------------------------------


def _make_docx(paragraphs: list[str], table_rows: list[list[str]] | None = None) -> bytes:
    """Build a .docx file in memory from paragraphs and optional table rows."""
    import docx

    doc = docx.Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    if table_rows:
        cols = max(len(r) for r in table_rows)
        table = doc.add_table(rows=len(table_rows), cols=cols)
        for i, row in enumerate(table_rows):
            for j, cell_text in enumerate(row):
                table.rows[i].cells[j].text = cell_text
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def _make_xlsx(rows: list[list]) -> bytes:
    """Build an .xlsx file in memory from a list of rows.

    First row is the header. Returns raw bytes suitable for upload.
    """
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# --- OneNote text parsing (internal helpers) ---------------------------------


class TestParseOnenoteText:
    """Verify parse_onenote_text handles various OneNote formats."""

    def test_bullet_points(self):
        from import_service import parse_onenote_text

        text = "- Buy groceries\n- Call dentist\n- Review report"
        result = parse_onenote_text(text)
        assert len(result) == 3
        assert result[0]["title"] == "Buy groceries"
        assert result[1]["title"] == "Call dentist"

    def test_numbered_list(self):
        from import_service import parse_onenote_text

        text = "1. First task\n2. Second task\n3) Third task"
        result = parse_onenote_text(text)
        assert len(result) == 3
        assert result[0]["title"] == "First task"
        assert result[2]["title"] == "Third task"

    def test_checkbox_items(self):
        from import_service import parse_onenote_text

        text = "\u2610 Unchecked item\n[ ] Another unchecked\n[x] Checked item"
        result = parse_onenote_text(text)
        assert len(result) == 3
        assert result[0]["title"] == "Unchecked item"

    def test_asterisk_bullets(self):
        from import_service import parse_onenote_text

        text = "* Star bullet one\n* Star bullet two"
        result = parse_onenote_text(text)
        assert len(result) == 2
        assert result[0]["title"] == "Star bullet one"

    def test_skips_empty_lines(self):
        from import_service import parse_onenote_text

        text = "- Task one\n\n\n- Task two\n   \n- Task three"
        result = parse_onenote_text(text)
        assert len(result) == 3

    def test_skips_header_lines(self):
        from import_service import parse_onenote_text

        text = "MEETING NOTES\n- Buy groceries\n2026-04-06\n- Call dentist"
        result = parse_onenote_text(text)
        assert len(result) == 2
        assert result[0]["title"] == "Buy groceries"

    def test_skips_date_headers(self):
        from import_service import parse_onenote_text

        text = "April 6, 2026\n- Task after date"
        result = parse_onenote_text(text)
        assert len(result) == 1
        assert result[0]["title"] == "Task after date"

    def test_deduplicates_within_paste(self):
        from import_service import parse_onenote_text

        text = "- Buy milk\n- Buy Milk\n- buy milk"
        result = parse_onenote_text(text)
        assert len(result) == 1

    def test_empty_text_returns_empty(self):
        from import_service import parse_onenote_text

        assert parse_onenote_text("") == []
        assert parse_onenote_text("   \n  ") == []

    def test_plain_lines_without_bullets(self):
        from import_service import parse_onenote_text

        text = "Schedule meeting with team\nReview Q2 numbers"
        result = parse_onenote_text(text)
        assert len(result) == 2

    def test_all_candidates_default_to_work(self):
        from import_service import parse_onenote_text

        result = parse_onenote_text("- A task")
        assert result[0]["type"] == "work"
        assert result[0]["included"] is True

    def test_skips_very_short_lines(self):
        from import_service import parse_onenote_text

        text = "- x\n- Real task here"
        result = parse_onenote_text(text)
        assert len(result) == 1
        assert result[0]["title"] == "Real task here"

    def test_mixed_bullet_styles(self):
        from import_service import parse_onenote_text

        text = "- Dash bullet\n* Star bullet\n1. Numbered\n\u2610 Checkbox"
        result = parse_onenote_text(text)
        assert len(result) == 4


# --- OneNote .docx parsing ---------------------------------------------------


class TestParseOnenoteDocx:
    """Verify parse_onenote_docx handles Word documents from OneNote export."""

    def test_basic_paragraphs(self):
        from import_service import parse_onenote_docx

        docx_bytes = _make_docx(["- Buy groceries", "- Call dentist"])
        result = parse_onenote_docx(docx_bytes)
        assert len(result) == 2
        assert result[0]["title"] == "Buy groceries"
        assert result[1]["title"] == "Call dentist"

    def test_extracts_table_text(self):
        from import_service import parse_onenote_docx

        docx_bytes = _make_docx([], table_rows=[["Task from table"]])
        result = parse_onenote_docx(docx_bytes)
        assert len(result) == 1
        assert result[0]["title"] == "Task from table"

    def test_combines_paragraphs_and_tables(self):
        from import_service import parse_onenote_docx

        docx_bytes = _make_docx(
            ["- Paragraph task"],
            table_rows=[["Table task"]],
        )
        result = parse_onenote_docx(docx_bytes)
        assert len(result) == 2

    def test_skips_headers_in_docx(self):
        from import_service import parse_onenote_docx

        docx_bytes = _make_docx(["MEETING NOTES", "- Real task"])
        result = parse_onenote_docx(docx_bytes)
        assert len(result) == 1
        assert result[0]["title"] == "Real task"

    def test_deduplicates_in_docx(self):
        from import_service import parse_onenote_docx

        docx_bytes = _make_docx(["- Same task", "- Same Task", "- same task"])
        result = parse_onenote_docx(docx_bytes)
        assert len(result) == 1

    def test_empty_doc_returns_empty(self):
        from import_service import parse_onenote_docx

        docx_bytes = _make_docx([])
        result = parse_onenote_docx(docx_bytes)
        assert result == []

    def test_invalid_docx_raises(self):
        from import_service import parse_onenote_docx

        with pytest.raises(ValueError, match="Cannot read"):
            parse_onenote_docx(b"not a docx file")

    def test_candidates_default_to_work(self):
        from import_service import parse_onenote_docx

        docx_bytes = _make_docx(["- A task from docx"])
        result = parse_onenote_docx(docx_bytes)
        assert result[0]["type"] == "work"
        assert result[0]["included"] is True


# --- Excel goals parsing ----------------------------------------------------


class TestParseExcelGoals:
    """Verify parse_excel_goals handles various Excel formats."""

    def test_basic_goals(self):
        from import_service import parse_excel_goals

        xlsx = _make_xlsx([
            ["title", "category", "priority"],
            ["Run a marathon", "health", "must"],
            ["Learn Spanish", "personal_growth", "should"],
        ])
        result = parse_excel_goals(xlsx)
        assert len(result) == 2
        assert result[0]["title"] == "Run a marathon"
        assert result[0]["category"] == "health"
        assert result[1]["priority"] == "should"

    def test_all_columns(self):
        from import_service import parse_excel_goals

        xlsx = _make_xlsx([
            ["title", "category", "priority", "actions", "target_quarter", "status", "notes"],
            ["Goal A", "work", "must", "Do things", "Q2 2026", "in_progress", "Some notes"],
        ])
        result = parse_excel_goals(xlsx)
        assert len(result) == 1
        assert result[0]["actions"] == "Do things"
        assert result[0]["target_quarter"] == "Q2 2026"
        assert result[0]["status"] == "in_progress"
        assert result[0]["notes"] == "Some notes"

    def test_missing_title_column_raises(self):
        from import_service import parse_excel_goals

        xlsx = _make_xlsx([
            ["name", "category"],
            ["Goal", "work"],
        ])
        with pytest.raises(ValueError, match="title"):
            parse_excel_goals(xlsx)

    def test_skips_empty_title_rows(self):
        from import_service import parse_excel_goals

        xlsx = _make_xlsx([
            ["title", "category"],
            ["Valid goal", "work"],
            ["", "health"],
            [None, "work"],
        ])
        result = parse_excel_goals(xlsx)
        assert len(result) == 1

    def test_invalid_category_defaults_to_work(self):
        from import_service import parse_excel_goals

        xlsx = _make_xlsx([
            ["title", "category"],
            ["Goal", "invalid_cat"],
        ])
        result = parse_excel_goals(xlsx)
        assert result[0]["category"] == "work"

    def test_invalid_priority_defaults_to_should(self):
        from import_service import parse_excel_goals

        xlsx = _make_xlsx([
            ["title", "priority"],
            ["Goal", "extreme"],
        ])
        result = parse_excel_goals(xlsx)
        assert result[0]["priority"] == "should"

    def test_invalid_status_defaults_to_not_started(self):
        from import_service import parse_excel_goals

        xlsx = _make_xlsx([
            ["title", "status"],
            ["Goal", "unknown_status"],
        ])
        result = parse_excel_goals(xlsx)
        assert result[0]["status"] == "not_started"

    def test_deduplicates_within_file(self):
        from import_service import parse_excel_goals

        xlsx = _make_xlsx([
            ["title"],
            ["Same Goal"],
            ["Same Goal"],
            ["same goal"],
        ])
        result = parse_excel_goals(xlsx)
        assert len(result) == 1

    def test_empty_file_returns_empty(self):
        from import_service import parse_excel_goals

        xlsx = _make_xlsx([])
        result = parse_excel_goals(xlsx)
        assert result == []

    def test_header_only_returns_empty(self):
        from import_service import parse_excel_goals

        xlsx = _make_xlsx([["title", "category"]])
        result = parse_excel_goals(xlsx)
        assert result == []

    def test_invalid_file_raises(self):
        from import_service import parse_excel_goals

        with pytest.raises(ValueError, match="Cannot read"):
            parse_excel_goals(b"not an excel file at all")

    def test_case_insensitive_headers(self):
        from import_service import parse_excel_goals

        xlsx = _make_xlsx([
            ["Title", "Category", "Priority"],
            ["Goal A", "health", "must"],
        ])
        result = parse_excel_goals(xlsx)
        assert len(result) == 1
        assert result[0]["title"] == "Goal A"

    def test_title_only_file(self):
        from import_service import parse_excel_goals

        xlsx = _make_xlsx([
            ["title"],
            ["Minimal goal"],
        ])
        result = parse_excel_goals(xlsx)
        assert result[0]["category"] == "work"
        assert result[0]["priority"] == "should"


# --- Duplicate detection -----------------------------------------------------


class TestDuplicateDetection:
    """Verify duplicate detection against existing DB records."""

    def test_finds_duplicate_tasks(self, app):
        from import_service import find_duplicate_tasks

        with app.app_context():
            db.session.add(Task(title="Existing task", type=TaskType.WORK, tier=Tier.INBOX))
            db.session.commit()

            dupes = find_duplicate_tasks(["Existing task", "New task"])
            assert "Existing task" in dupes
            assert "New task" not in dupes

    def test_case_insensitive_task_duplicates(self, app):
        from import_service import find_duplicate_tasks

        with app.app_context():
            db.session.add(Task(title="Buy Milk", type=TaskType.WORK, tier=Tier.INBOX))
            db.session.commit()

            dupes = find_duplicate_tasks(["buy milk", "BUY MILK"])
            assert len(dupes) == 2

    def test_finds_duplicate_goals(self, app):
        from import_service import find_duplicate_goals

        with app.app_context():
            db.session.add(Goal(
                title="Learn Python",
                category=GoalCategory.WORK,
                priority=GoalPriority.SHOULD,
            ))
            db.session.commit()

            dupes = find_duplicate_goals(["Learn Python", "New Goal"])
            assert "Learn Python" in dupes
            assert "New Goal" not in dupes

    def test_empty_list_returns_empty(self, app):
        from import_service import find_duplicate_goals, find_duplicate_tasks

        with app.app_context():
            assert find_duplicate_tasks([]) == []
            assert find_duplicate_goals([]) == []


# --- Create tasks from import ------------------------------------------------


class TestCreateTasksFromImport:
    """Verify create_tasks_from_import creates records and logs."""

    def test_creates_included_tasks(self, app):
        from import_service import create_tasks_from_import

        with app.app_context():
            candidates = [
                {"title": "Task A", "type": "work", "included": True},
                {"title": "Task B", "type": "personal", "included": True},
            ]
            tasks = create_tasks_from_import(candidates, source="test_import")
            assert len(tasks) == 2
            assert tasks[0].title == "Task A"
            assert tasks[1].type == TaskType.PERSONAL

    def test_all_tasks_land_in_inbox(self, app):
        from import_service import create_tasks_from_import

        with app.app_context():
            tasks = create_tasks_from_import(
                [{"title": "Inbox item", "included": True}],
                source="test",
            )
            assert tasks[0].tier == Tier.INBOX

    def test_skips_excluded(self, app):
        from import_service import create_tasks_from_import

        with app.app_context():
            tasks = create_tasks_from_import(
                [
                    {"title": "Include", "included": True},
                    {"title": "Exclude", "included": False},
                ],
                source="test",
            )
            assert len(tasks) == 1

    def test_logs_import(self, app):
        from import_service import create_tasks_from_import

        with app.app_context():
            create_tasks_from_import(
                [{"title": "Logged task", "included": True}],
                source="onenote_test",
            )
            log = db.session.scalars(
                db.select(ImportLog).where(ImportLog.source == "onenote_test")
            ).first()
            assert log is not None
            assert log.task_count == 1

    def test_skips_empty_titles(self, app):
        from import_service import create_tasks_from_import

        with app.app_context():
            tasks = create_tasks_from_import(
                [{"title": "", "included": True}, {"title": "  ", "included": True}],
                source="test",
            )
            assert len(tasks) == 0


# --- Create goals from import ------------------------------------------------


class TestCreateGoalsFromImport:
    """Verify create_goals_from_import creates records and logs."""

    def test_creates_included_goals(self, app):
        from import_service import create_goals_from_import

        with app.app_context():
            candidates = [
                {"title": "Goal A", "category": "health", "priority": "must", "included": True},
                {"title": "Goal B", "category": "work", "priority": "should", "included": True},
            ]
            goals = create_goals_from_import(candidates, source="excel_test")
            assert len(goals) == 2
            assert goals[0].title == "Goal A"
            assert goals[0].category == GoalCategory.HEALTH

    def test_skips_excluded(self, app):
        from import_service import create_goals_from_import

        with app.app_context():
            goals = create_goals_from_import(
                [
                    {"title": "Include", "category": "work", "priority": "must", "included": True},
                    {"title": "Exclude", "category": "work", "priority": "must", "included": False},
                ],
                source="test",
            )
            assert len(goals) == 1

    def test_logs_import(self, app):
        from import_service import create_goals_from_import

        with app.app_context():
            create_goals_from_import(
                [{"title": "Logged goal", "category": "work",
                  "priority": "must", "included": True}],
                source="excel_goals_test",
            )
            log = db.session.scalars(
                db.select(ImportLog).where(ImportLog.source == "excel_goals_test")
            ).first()
            assert log is not None
            assert log.task_count == 1

    def test_invalid_category_defaults_to_work(self, app):
        from import_service import create_goals_from_import

        with app.app_context():
            goals = create_goals_from_import(
                [{"title": "Bad cat", "category": "invalid", "priority": "must", "included": True}],
                source="test",
            )
            assert goals[0].category == GoalCategory.WORK

    def test_invalid_priority_defaults_to_should(self, app):
        from import_service import create_goals_from_import

        with app.app_context():
            goals = create_goals_from_import(
                [{"title": "Bad pri", "category": "work", "priority": "extreme", "included": True}],
                source="test",
            )
            assert goals[0].priority == GoalPriority.SHOULD


# --- Tasks parse API endpoint ------------------------------------------------


class TestTasksParseAPI:
    """Verify POST /api/import/tasks/parse."""

    def test_parse_returns_candidates(self, authed_client):
        resp = authed_client.post(
            "/api/import/tasks/parse",
            json={"text": "- Buy groceries\n- Call dentist"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total"] == 2
        assert body["candidates"][0]["title"] == "Buy groceries"

    def test_no_json_returns_400(self, authed_client):
        resp = authed_client.post(
            "/api/import/tasks/parse",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_empty_text_returns_400(self, authed_client):
        resp = authed_client.post(
            "/api/import/tasks/parse",
            json={"text": ""},
        )
        assert resp.status_code == 400

    def test_flags_duplicates(self, authed_client, app):
        with app.app_context():
            db.session.add(Task(title="Existing", type=TaskType.WORK, tier=Tier.INBOX))
            db.session.commit()

        resp = authed_client.post(
            "/api/import/tasks/parse",
            json={"text": "- Existing\n- Brand new task"},
        )
        body = resp.get_json()
        dupes = [c for c in body["candidates"] if c["duplicate"]]
        non_dupes = [c for c in body["candidates"] if not c["duplicate"]]
        assert len(dupes) == 1
        assert dupes[0]["title"] == "Existing"
        assert len(non_dupes) == 1


# --- Tasks upload (.docx) API endpoint ---------------------------------------


class TestTasksUploadAPI:
    """Verify POST /api/import/tasks/upload."""

    def test_upload_returns_candidates(self, authed_client):
        docx_bytes = _make_docx(["- Buy groceries", "- Call dentist"])
        data = {
            "file": (
                io.BytesIO(docx_bytes),
                "notes.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        resp = authed_client.post(
            "/api/import/tasks/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total"] == 2
        assert body["candidates"][0]["title"] == "Buy groceries"

    def test_no_file_returns_400(self, authed_client):
        resp = authed_client.post("/api/import/tasks/upload")
        assert resp.status_code == 400

    def test_wrong_extension_returns_422(self, authed_client):
        data = {"file": (io.BytesIO(b"data"), "notes.txt", "text/plain")}
        resp = authed_client.post(
            "/api/import/tasks/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 422

    def test_empty_file_returns_400(self, authed_client):
        data = {
            "file": (
                io.BytesIO(b""),
                "empty.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        resp = authed_client.post(
            "/api/import/tasks/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_invalid_docx_returns_422(self, authed_client):
        data = {
            "file": (
                io.BytesIO(b"not a docx"),
                "bad.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        resp = authed_client.post(
            "/api/import/tasks/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 422

    def test_flags_duplicate_tasks(self, authed_client, app):
        with app.app_context():
            db.session.add(Task(title="Existing", type=TaskType.WORK, tier=Tier.INBOX))
            db.session.commit()

        docx_bytes = _make_docx(["- Existing", "- Brand new task"])
        data = {
            "file": (
                io.BytesIO(docx_bytes),
                "notes.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        resp = authed_client.post(
            "/api/import/tasks/upload",
            data=data,
            content_type="multipart/form-data",
        )
        body = resp.get_json()
        dupes = [c for c in body["candidates"] if c["duplicate"]]
        assert len(dupes) == 1
        assert dupes[0]["title"] == "Existing"


# --- Tasks confirm API endpoint ----------------------------------------------


class TestTasksConfirmAPI:
    """Verify POST /api/import/tasks/confirm."""

    def test_confirm_creates_tasks(self, authed_client):
        resp = authed_client.post(
            "/api/import/tasks/confirm",
            json={
                "candidates": [
                    {"title": "New task A", "type": "work", "included": True},
                    {"title": "New task B", "type": "personal", "included": True},
                ],
                "source": "onenote_test",
            },
        )
        assert resp.status_code == 201
        assert resp.get_json()["created"] == 2

    def test_confirm_skips_excluded(self, authed_client):
        resp = authed_client.post(
            "/api/import/tasks/confirm",
            json={
                "candidates": [
                    {"title": "Include", "included": True},
                    {"title": "Exclude", "included": False},
                ],
            },
        )
        assert resp.status_code == 201
        assert resp.get_json()["created"] == 1

    def test_confirmed_tasks_in_inbox(self, authed_client):
        authed_client.post(
            "/api/import/tasks/confirm",
            json={"candidates": [{"title": "Imported task", "included": True}]},
        )
        resp = authed_client.get("/api/tasks?tier=inbox")
        titles = [t["title"] for t in resp.get_json()]
        assert "Imported task" in titles

    def test_no_json_returns_400(self, authed_client):
        resp = authed_client.post(
            "/api/import/tasks/confirm",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_invalid_candidates_returns_422(self, authed_client):
        resp = authed_client.post(
            "/api/import/tasks/confirm",
            json={"candidates": "not a list"},
        )
        assert resp.status_code == 422


# --- Goals parse API endpoint ------------------------------------------------


class TestGoalsParseAPI:
    """Verify POST /api/import/goals/parse."""

    def test_parse_returns_candidates(self, authed_client):
        xlsx = _make_xlsx([
            ["title", "category", "priority"],
            ["Run marathon", "health", "must"],
        ])
        data = {"file": (io.BytesIO(xlsx), "goals.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        resp = authed_client.post(
            "/api/import/goals/parse",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total"] == 1
        assert body["candidates"][0]["title"] == "Run marathon"

    def test_no_file_returns_400(self, authed_client):
        resp = authed_client.post("/api/import/goals/parse")
        assert resp.status_code == 400

    def test_wrong_extension_returns_422(self, authed_client):
        data = {"file": (io.BytesIO(b"data"), "goals.csv", "text/csv")}
        resp = authed_client.post(
            "/api/import/goals/parse",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 422

    def test_empty_file_returns_400(self, authed_client):
        data = {"file": (io.BytesIO(b""), "empty.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        resp = authed_client.post(
            "/api/import/goals/parse",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_invalid_excel_returns_422(self, authed_client):
        data = {"file": (io.BytesIO(b"not excel"), "bad.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        resp = authed_client.post(
            "/api/import/goals/parse",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 422

    def test_flags_duplicate_goals(self, authed_client, app):
        with app.app_context():
            db.session.add(Goal(
                title="Existing Goal",
                category=GoalCategory.WORK,
                priority=GoalPriority.SHOULD,
            ))
            db.session.commit()

        xlsx = _make_xlsx([
            ["title"],
            ["Existing Goal"],
            ["New Goal"],
        ])
        data = {"file": (io.BytesIO(xlsx), "goals.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        resp = authed_client.post(
            "/api/import/goals/parse",
            data=data,
            content_type="multipart/form-data",
        )
        body = resp.get_json()
        dupes = [c for c in body["candidates"] if c["duplicate"]]
        assert len(dupes) == 1
        assert dupes[0]["title"] == "Existing Goal"


# --- Goals confirm API endpoint ----------------------------------------------


class TestGoalsConfirmAPI:
    """Verify POST /api/import/goals/confirm."""

    def test_confirm_creates_goals(self, authed_client):
        resp = authed_client.post(
            "/api/import/goals/confirm",
            json={
                "candidates": [
                    {"title": "Goal A", "category": "health", "priority": "must", "included": True},
                ],
                "source": "excel_test",
            },
        )
        assert resp.status_code == 201
        assert resp.get_json()["created"] == 1

    def test_confirm_skips_excluded(self, authed_client):
        resp = authed_client.post(
            "/api/import/goals/confirm",
            json={
                "candidates": [
                    {"title": "Include", "category": "work", "priority": "must", "included": True},
                    {"title": "Exclude", "category": "work", "priority": "must", "included": False},
                ],
            },
        )
        assert resp.status_code == 201
        assert resp.get_json()["created"] == 1

    def test_no_json_returns_400(self, authed_client):
        resp = authed_client.post(
            "/api/import/goals/confirm",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_invalid_candidates_returns_422(self, authed_client):
        resp = authed_client.post(
            "/api/import/goals/confirm",
            json={"candidates": "not a list"},
        )
        assert resp.status_code == 422

    def test_empty_candidates_returns_zero(self, authed_client):
        resp = authed_client.post(
            "/api/import/goals/confirm",
            json={"candidates": []},
        )
        assert resp.status_code == 201
        assert resp.get_json()["created"] == 0


# --- Import page HTML --------------------------------------------------------


class TestImportPageView:
    """Verify the /import page renders with the expected structure."""

    def test_renders_200(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        resp = client.get("/import")
        assert resp.status_code == 200

    def test_has_mode_buttons(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/import").data.decode()
        assert 'id="importTasksBtn"' in html
        assert 'id="importDocxBtn"' in html
        assert 'id="importGoalsBtn"' in html

    def test_has_text_input(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/import").data.decode()
        assert 'id="importText"' in html

    def test_has_file_input(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/import").data.decode()
        assert 'id="importFile"' in html
        assert ".xlsx" in html

    def test_has_docx_upload(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/import").data.decode()
        assert 'id="importDocxFile"' in html
        assert ".docx" in html

    def test_has_review_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/import").data.decode()
        assert 'id="importReview"' in html
        assert 'id="importCandidates"' in html

    def test_has_confirm_buttons(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/import").data.decode()
        assert 'id="importConfirmAll"' in html
        assert 'id="importConfirmSelected"' in html

    def test_has_confirm_summary_section(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/import").data.decode()
        assert 'id="importConfirm"' in html
        assert 'id="importConfirmList"' in html
        assert 'id="importFinalConfirm"' in html
        assert 'id="importGoBackBtn"' in html
        assert 'id="importCancelBtn"' in html

    def test_loads_import_js(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: "me@example.com")
        html = client.get("/import").data.decode()
        assert "import.js" in html

    def test_requires_auth(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_current_user_email", lambda: None)
        resp = client.get("/import")
        assert resp.status_code == 302


# --- Blueprint registration --------------------------------------------------


class TestImportBlueprint:
    """Verify the import_api blueprint is registered."""

    def test_blueprint_registered(self, app):
        assert "import_api" in app.blueprints

    def test_routes_exist(self, app):
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/import/tasks/parse" in rules
        assert "/api/import/tasks/confirm" in rules
        assert "/api/import/goals/parse" in rules
        assert "/api/import/tasks/upload" in rules
        assert "/api/import/goals/confirm" in rules
