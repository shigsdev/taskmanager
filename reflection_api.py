"""JSON API for the Weekly Reflection feature.

Endpoints:
    POST   /api/reflection                       — submit a reflection (typed
        JSON {"text": ...} OR multipart audio field "audio"); transcribes
        if audio, persists the Reflection, returns AI-proposed actions
    POST   /api/reflection/transcribe-segment    — transcribe ONE audio
        segment (#232 pause+resume). No Reflection row, no Claude call —
        just audio→text. Frontend appends the text to its textarea and
        eventually POSTs the merged content to the main endpoint above.
    POST   /api/reflection/attachment            — #328: attach ONE context
        document (multipart field "file"; pdf/docx/xlsx/txt/md/image).
        Extracted to text in memory; the file itself is never stored.
        The text lands on the open draft and rides onto the reflection.
    DELETE /api/reflection/attachment/<id>       — #328: detach one
    GET    /api/reflection/global-context        — #336: list the documents
        attached to EVERY reflection
    POST   /api/reflection/global-context        — #336: upload one (same
        extraction path as /attachment; only the filing differs)
    POST   /api/reflection/attachment/<id>/make-global
                                                 — #336: MOVE one of this
        reflection's attachments into the global store. Free — the text
        already exists, so no extraction and no paid call.
    DELETE /api/reflection/global-context/<id>   — #336: stop one riding along
    POST   /api/reflection/<id>/confirm          — apply the user-selected
        actions; returns an apply summary
    POST   /api/reflection/analyze-together      — #335: read several past
        reflections in ONE analysis. Full transcripts (not the 1200-char
        continuity snippet) plus the de-duplicated union of their attached
        documents; creates a new synthesis row, sources untouched.
    POST   /api/reflection/<id>/continue         — #334: FORK a saved
        reflection into a new draft (its text, voice segments and attached
        documents); the parent row is never modified. 409 if a draft
        holding work is already open. Free — no Whisper, no Claude.
    POST   /api/reflection/<id>/archive          — #238: hide from default
        history list (toggleable; "Show archived" surfaces it again)
    POST   /api/reflection/<id>/unarchive        — #238: restore from archive
    DELETE /api/reflection/<id>                  — #238: soft-delete
        (`is_active=False`); row stays in DB, surfaces in
        Recently-deleted UI section
    POST   /api/reflection/<id>/restore          — #238: restore from
        soft-delete
    GET    /api/reflection                       — list past reflections;
        ``?include_archived=true``/``?include_deleted=true`` opt-in flags
    GET    /api/reflection/<id>                  — one reflection + its
        proposed/applied actions (history detail)

The transcript is always persisted (the user explicitly wants every
reflection kept for future reference). Audio is processed in memory only
on the SERVER — never written to server disk or the DB (handled by
voice_service). #327 buffers in-flight audio transiently in the browser's
IndexedDB on the user's own device so an interrupted recording survives;
that device-local copy is deleted as soon as the segment is transcribed.

#328 attachments follow the same server posture as audio and /scan
images: the uploaded file is decoded to text in memory and the bytes are
dropped when the request ends. Only the extracted TEXT is persisted.
Because that text is untrusted input feeding a prompt that can propose
deletes, it is fenced and marked data-not-instructions — see
``reflection_context_service`` and ADR-037.

#336 adds a SECOND store for the same extracted text: documents marked
always-attached live in ``global_context_files`` and are merged into
every analysis. The two share ONE budget, so marking something global
buys no extra room in the prompt. A global document is NOT copied onto
each reflection row — that store is the record of what rode along.
"""
from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request

from auth import login_required
from global_context_service import (
    add_global_file,
    list_global_files,
    merged_context_files,
    remove_global_file,
)
from milestone_service import clear_milestone, get_milestone, set_milestone
from models import ReflectionInputMode
from rate_limit import PAID_API, limiter
from reflection_context_service import (
    ALLOWED_EXTENSIONS,
    MAX_FILES,
    MAX_TOTAL_CHARS,
    MAX_UPLOAD_BYTES,
    ContextExtractionError,
    build_attachment,
    check_capacity,
    normalise_context_files,
    public_view,
    total_chars,
)
from reflection_service import (
    CombinedSelectionError,
    DraftAlreadyOpen,
    analyze_reflection,
    apply_selected_actions,
    attach_analysis,
    combined_transcript,
    continue_reflection,
    create_synthesis,
    discard_draft,
    get_open_draft,
    get_reflection,
    list_reflections,
    merged_source_files,
    reset_applied_state,
    resolve_combined_sources,
    save_draft,
    save_reflection,
    set_reflection_title,
    synthesis_sources_of,
)
from utils import validate_json_body, validate_upload
from voice_service import (
    ALLOWED_AUDIO_TYPES,
    WHISPER_MAX_UPLOAD_BYTES,
    transcribe_audio,
)

logger = logging.getLogger(__name__)

bp = Blueprint("reflection_api", __name__, url_prefix="/api/reflection")


def _lineage(parent) -> dict | None:
    """#334: the minimum a client needs to NAME the forked-from sitting.

    Exactly the fields `reflection_helpers.reflectionLabel()` reads, so
    the label rule lives in one place instead of being reimplemented for
    the lineage line. Deliberately NOT the transcript — a parent can be
    tens of thousands of characters and it would ride along on every
    history row and every draft autosave response.
    """
    if parent is None:
        return None
    return {
        "id": str(parent.id),
        "title": parent.title,
        "iso_week": parent.iso_week,
        "input_mode": parent.input_mode.value,
        "created_at": (
            parent.created_at.isoformat() if parent.created_at else None
        ),
    }


def _serialize(reflection) -> dict:
    proposed = reflection.proposed_actions or {}
    return {
        "id": str(reflection.id),
        "iso_week": reflection.iso_week,
        # #339: NULL means unnamed; the client falls back to a generated
        # label rather than the server inventing one, so the same rule
        # applies to a brand-new reflection that has never been saved.
        "title": reflection.title,
        "input_mode": reflection.input_mode.value,
        "transcript": reflection.transcript,
        "audio_duration_seconds": reflection.audio_duration_seconds,
        "audio_cost_usd": reflection.audio_cost_usd,
        "ai_cost_usd": reflection.ai_cost_usd,
        "proposed_actions": {
            "explicit": proposed.get("explicit", []),
            "suggested": proposed.get("suggested", []),
        },
        # #237 (2026-05-26): raw per-segment Whisper transcripts from
        # the #232 pause/resume flow. Empty list for typed reflections
        # and for pre-#237 voice reflections.
        "raw_segments": reflection.raw_segments or [],
        # #238 (2026-05-26): archive + soft-delete flags. UI uses these
        # to render archived rows muted and to surface restore buttons
        # on the Recently-deleted list.
        "is_archived": bool(reflection.is_archived),
        "is_active": bool(reflection.is_active),
        # #324: unsubmitted draft (no analysis yet, hidden from history).
        "is_draft": bool(reflection.is_draft),
        # #334: lineage. The id alone would force the client to hunt for
        # the parent in whatever list it happens to hold (and fail when
        # the parent is archived and filtered out), so the few fields
        # `reflectionLabel()` needs travel with it. Eager-loaded via the
        # model's joined relationship, so a whole history page costs one
        # statement — see the measurement note on Reflection.continued_from.
        "continued_from_id": (
            str(reflection.continued_from_id)
            if reflection.continued_from_id else None
        ),
        "continued_from": _lineage(reflection.continued_from),
        # #335: the ids this row is a combined analysis of, or null. Ids
        # only -- the sittings are already NAMED in this row's own
        # transcript, so resolving each one here would add a query per
        # history row to render text the client already has.
        "synthesis_of": list(reflection.synthesis_of or []) or None,
        # #328: attached context documents. METADATA ONLY — the extracted
        # text can be tens of thousands of characters, the UI never
        # renders it, and it would ride along on every draft autosave
        # response.
        "context_files": public_view(reflection.context_files),
        # The client shows this as "last saved" on a restored draft.
        "updated_at": (
            reflection.updated_at.isoformat() if reflection.updated_at else None
        ),
        "applied_actions": reflection.applied_actions,
        "applied_at": (
            reflection.applied_at.isoformat()
            if reflection.applied_at
            else None
        ),
        "created_at": reflection.created_at.isoformat(),
    }


@bp.post("")
@login_required
@limiter.limit(PAID_API)  # paid: Whisper (audio) + Claude
def submit(email: str):  # noqa: ARG001
    """Submit a reflection. Accepts EITHER multipart/form-data with an
    'audio' file field OR a JSON body ``{"text": "..."}``.

    Returns the persisted reflection id, transcript, and the AI's
    proposed actions (explicit + suggested buckets). Nothing is written
    to projects/goals/tasks until the /confirm endpoint runs.
    """
    audio_file = request.files.get("audio")
    duration = None
    audio_cost = None

    if audio_file is not None:
        audio_bytes, content_type, err = validate_upload(
            request,
            field_name="audio",
            allowed_mime=ALLOWED_AUDIO_TYPES,
            max_bytes=WHISPER_MAX_UPLOAD_BYTES,
        )
        if err:
            body, status = err
            if status == 422:
                logger.warning(
                    "reflection audio rejected: %s", body.get("error")
                )
            return jsonify(body), status
        try:
            result = transcribe_audio(audio_bytes, content_type)
        except RuntimeError as e:
            logger.warning("Reflection transcription failed: %s", e)
            return jsonify({"error": f"Transcription failed: {e}"}), 422
        except Exception:
            logger.exception("Reflection transcription crashed")
            return jsonify(
                {"error": "Transcription failed (unexpected)"}
            ), 500
        transcript = result["transcript"]
        duration = result["duration_seconds"]
        audio_cost = result["cost_usd"]
        input_mode = ReflectionInputMode.VOICE
    else:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "JSON body or audio file required"}), 400
        transcript = (data.get("text") or "").strip()
        input_mode = ReflectionInputMode.TYPED

    if not transcript or not transcript.strip():
        return jsonify({
            "error": "Reflection is empty — nothing to analyze",
        }), 422

    # #237 (2026-05-26): the JSON path also carries `raw_segments` —
    # the per-segment Whisper transcripts the user accumulated via
    # the #232 pause/resume flow. Persisted alongside the final
    # (possibly edited) `transcript` so an edit doesn't lose the
    # original spoken words. Only the JSON path has this — the
    # audio-upload path is a single-shot recording with no segments
    # (kept for back-compat / direct one-shot voice memos).
    raw_segments: list | None = None
    if audio_file is None:
        rs = data.get("raw_segments") if isinstance(data, dict) else None
        if isinstance(rs, list):
            raw_segments = rs
            # If raw_segments were sent, this came from the #232
            # pause/resume flow — mark as VOICE input even though the
            # final POST is JSON (the textarea content was assembled
            # from voice transcripts).
            if rs:
                input_mode = ReflectionInputMode.VOICE

    # #328: the open draft carries any context documents attached over
    # this (possibly multi-sitting) reflection. Read them BEFORE the
    # draft is retired below, so they ride onto the reflection row and
    # into the analysis rather than being dropped with the draft.
    open_draft = get_open_draft()
    context_files = normalise_context_files(
        open_draft.context_files if open_draft else []
    )
    # #336: always-attached documents ride along with the ANALYSIS but are
    # deliberately NOT copied onto the row. They live in their own store,
    # which is the record of what was attached; duplicating tens of
    # thousands of characters onto every sitting is exactly the cost that
    # feature exists to remove.
    analysis_files = merged_context_files(context_files)
    # #334: if this sitting was forked from a past reflection, the lineage
    # lives on the draft. Read it here for the same reason as the
    # attachments above — `discard_draft()` below is a hard delete, so
    # anything still only on the draft is gone a few lines from now.
    continued_from_id = open_draft.continued_from_id if open_draft else None
    continued_from = open_draft.continued_from if open_draft else None

    # Persist the transcript FIRST, before the paid + failure-prone
    # Claude call. #165 requires every transcript persisted forever;
    # the original order (analyze → save) discarded the reflection on
    # any Claude failure — worst case losing a voice memo that already
    # cost a Whisper transcription. proposed_actions starts empty and
    # gets attached on analysis success.
    reflection = save_reflection(
        transcript=transcript,
        input_mode=input_mode,
        proposed={"explicit": [], "suggested": []},
        audio_duration_seconds=duration,
        audio_cost_usd=audio_cost,
        ai_cost_usd=None,
        raw_segments=raw_segments,  # #237
        context_files=context_files,  # #328
        continued_from_id=continued_from_id,  # #334
    )

    # #324: the draft has become a real reflection — retire it. Done
    # HERE, right after the transcript is durably saved and BEFORE the
    # failure-prone Claude call, so the text exists in exactly one place
    # at every instant: never zero (that would lose the reflection) and
    # never two (a stale draft would reappear on the next page load and
    # invite a duplicate submit).
    discard_draft()

    # Analyze with Claude (proposes create/update/delete actions). On
    # failure the reflection is ALREADY saved — return its id + the
    # error so the client shows "saved, analysis failed — retry" and
    # the transcript is visible in the history list, NOT lost.
    try:
        # #325: exclude THIS reflection from its own continuity context.
        # #328: attached documents come along as explicitly-untrusted
        # reference material (see reflection_context_service / ADR-037).
        analysis = analyze_reflection(
            transcript,
            exclude_id=reflection.id,
            context_files=analysis_files,  # #336: session + always-attached
            # #334: names the carried-over sitting and keeps it out of the
            # continuity list, where its text would appear a second time.
            continued_from=continued_from,
        )
    except RuntimeError as e:
        logger.warning(
            "Reflection analysis failed (transcript %s saved): %s",
            reflection.id, e,
        )
        return jsonify({
            "error": f"Analysis failed: {e}",
            "reflection_id": str(reflection.id),
            "saved": True,
        }), 422
    except Exception:
        logger.exception(
            "Reflection analysis crashed unexpectedly "
            "(transcript %s saved)", reflection.id,
        )
        return jsonify({
            "error": "Analysis failed (unexpected)",
            "reflection_id": str(reflection.id),
            "saved": True,
        }), 500

    reflection = attach_analysis(
        reflection,
        proposed={
            "explicit": analysis["explicit"],
            "suggested": analysis["suggested"],
        },
        ai_cost_usd=analysis["ai_cost_usd"],
    )

    return jsonify(_serialize(reflection)), 201


@bp.post("/transcribe-segment")
@login_required
@limiter.limit(PAID_API)  # paid: Whisper
def transcribe_segment(email: str):  # noqa: ARG001
    """Transcribe ONE audio segment for the #232 pause+resume flow.

    Accepts multipart/form-data with an 'audio' file field (same MIME
    whitelist + size cap as ``POST /api/reflection``). Returns just the
    raw transcription — no Reflection row is saved, no Claude analysis
    is run. The frontend appends the returned text to its shared
    ``#reflText`` textarea; when the user clicks Done it POSTs the full
    merged content to ``POST /api/reflection`` (text path), which runs
    the persist + Claude steps exactly as before.

    This decoupling keeps cost predictable (one Whisper call per
    segment, one Claude call per finalized reflection) and bounds the
    blast radius of a network blip: if one segment fails the
    frontend retries that segment only; prior segments' text is already
    in the textarea and unaffected.

    Returns JSON::

        {
            "transcript": "...",
            "duration_seconds": 12.5,
            "cost_usd": 0.0012
        }
    """
    audio_bytes, content_type, err = validate_upload(
        request,
        field_name="audio",
        allowed_mime=ALLOWED_AUDIO_TYPES,
        max_bytes=WHISPER_MAX_UPLOAD_BYTES,
    )
    if err:
        body, status = err
        if status == 422:
            logger.warning(
                "reflection segment rejected: %s", body.get("error"),
            )
        return jsonify(body), status

    try:
        result = transcribe_audio(audio_bytes, content_type)
    except RuntimeError as e:
        logger.warning("Reflection segment transcription failed: %s", e)
        return jsonify({"error": f"Transcription failed: {e}"}), 422
    except Exception:
        logger.exception("Reflection segment transcription crashed")
        return jsonify(
            {"error": "Transcription failed (unexpected)"}
        ), 500

    return jsonify({
        "transcript": result["transcript"],
        "duration_seconds": result["duration_seconds"],
        "cost_usd": result["cost_usd"],
    })


@bp.post("/<uuid:reflection_id>/confirm")
@login_required
@validate_json_body
def confirm(email: str, reflection_id):  # noqa: ARG001
    """Apply the user-confirmed actions for a reflection.

    Expects JSON ``{"actions": [ <normalized action>, ... ]}`` — the
    subset of proposed actions the user checked (optionally edited).
    Re-validated server-side through the service layer; creations are
    grouped for recycle-bin undo, deletes are soft.
    """
    reflection = get_reflection(reflection_id)
    if reflection is None:
        return jsonify({"error": "Reflection not found"}), 404

    data = g.json_body
    actions = data.get("actions", [])
    if not isinstance(actions, list):
        return jsonify({"error": "actions must be a list"}), 422

    if reflection.applied_at is not None:
        return jsonify({
            "error": "This reflection has already been applied",
        }), 409

    try:
        summary = apply_selected_actions(reflection, actions)
    except Exception:
        # #174 (2026-05-21): apply_selected_actions is now exception-safe
        # — every step captures its own failure in summary["errors"] and
        # the function always returns a summary. This catch-all is a
        # genuine last resort (e.g. a bug in the summary-building itself)
        # and should almost never fire.
        logger.exception("Reflection apply crashed unexpectedly")
        return jsonify({"error": "Apply failed (unexpected)"}), 500

    # #174: surface partial success. apply_selected_actions records
    # per-step failures in summary["errors"] rather than aborting — so
    # a non-empty errors list means SOME actions landed and some did
    # not. Return 207 Multi-Status in that case so the client (and any
    # future automation) can tell "fully applied" from "partially
    # applied" without diffing the counts. `applied_at` is None when the
    # final audit-record commit itself failed — guard the .isoformat().
    status = 207 if summary.get("errors") else 200
    return jsonify({
        "id": str(reflection.id),
        "summary": summary,
        "applied_at": (
            reflection.applied_at.isoformat()
            if reflection.applied_at is not None
            else None
        ),
    }), status


# --- Drafts: reflecting across several sittings (#324) ----------------------
# Free endpoints — no Whisper, no Claude, so no PAID_API limit. The draft
# lives server-side (not localStorage) so it follows the user from phone
# to laptop and survives an evicted PWA.


@bp.get("/draft")
@login_required
def get_draft(email: str):  # noqa: ARG001
    """The open draft, or ``{"draft": null}`` when there isn't one."""
    draft = get_open_draft()
    return jsonify({"draft": _serialize(draft) if draft else None})


@bp.put("/draft")
@login_required
@validate_json_body
def put_draft(email: str):  # noqa: ARG001
    """Autosave the in-progress reflection.

    Body: ``{"text": "...", "raw_segments": [...]}``. Upserts the single
    open draft. An empty ``text`` is allowed on purpose — the user
    clearing the box is a state worth saving, and rejecting it would
    strand the client's autosave loop.
    """
    data = g.json_body
    text = data.get("text")
    if text is not None and not isinstance(text, str):
        return jsonify({"error": "text must be a string"}), 422
    raw_segments = data.get("raw_segments")
    if raw_segments is not None and not isinstance(raw_segments, list):
        return jsonify({"error": "raw_segments must be a list"}), 422
    # NOTE: context_files is deliberately NOT accepted here. Attachments
    # are added and removed through the /attachment endpoints below; the
    # autosave loop sends only text, and letting it also write the
    # attachment list would let a stale in-flight save resurrect a file
    # the user just removed.
    draft = save_draft(transcript=text or "", raw_segments=raw_segments)
    return jsonify({"draft": _serialize(draft)}), 200


@bp.delete("/draft")
@login_required
def delete_draft(email: str):  # noqa: ARG001
    """Discard the open draft. 204 either way — idempotent."""
    discard_draft()
    return "", 204


# --- Context documents (#328) -----------------------------------------------
# Attach reference material — a job description, a 30/60/90 plan, a photo
# of a whiteboard — so the analysis reasons against more than the user's
# words. The FILE is never stored: it is decoded to text in memory and
# the bytes are dropped when the request ends. Only the extracted text is
# persisted, on the draft (and from there onto the submitted reflection).
#
# Attachments live on the draft rather than in the browser so they follow
# the user across sittings and devices, exactly like the draft text
# itself (#324).


def _attachment_payload(draft) -> dict:
    files = normalise_context_files(draft.context_files if draft else [])
    # #336: the budget counters report the MERGED total, because that is
    # the number that decides whether the next upload is refused. Showing
    # only this reflection's share would let the user watch a counter sit
    # at 12,000 / 60,000 and still be turned away.
    merged = merged_context_files(files)
    return {
        "context_files": public_view(files),
        "global_files": public_view(list_global_files()),
        "total_chars": total_chars(merged),
        "session_chars": total_chars(files),
        "file_count": len(merged),
        "max_total_chars": MAX_TOTAL_CHARS,
        "max_files": MAX_FILES,
    }


def _global_payload() -> dict:
    """The always-attached list, with the same shared-budget counters.

    Separate from :func:`_attachment_payload` because the global routes
    have no draft to report on, but it carries the same totals so both
    panels can show one honest budget rather than two half-truths.
    """
    draft = get_open_draft()
    session_files = normalise_context_files(draft.context_files if draft else [])
    merged = merged_context_files(session_files)
    return {
        "files": public_view(list_global_files()),
        "total_chars": total_chars(merged),
        "file_count": len(merged),
        "max_total_chars": MAX_TOTAL_CHARS,
        "max_files": MAX_FILES,
    }


@bp.post("/attachment")
@login_required
@limiter.limit(PAID_API)  # paid: image attachments hit Google Vision OCR
def add_attachment(email: str):  # noqa: ARG001
    """Attach one context document to the open draft.

    Accepts multipart/form-data with a 'file' field. Validates on
    EXTENSION rather than Content-Type because the extension is what
    selects the extractor, and browsers report unreliable MIME types for
    .md / .docx / .xlsx (the same reasoning as the import routes, #194).

    Returns the new attachment's metadata plus the full attachment list.
    """
    file_bytes, _ct, err = validate_upload(
        request,
        field_name="file",
        max_bytes=MAX_UPLOAD_BYTES,
        allowed_extensions=ALLOWED_EXTENSIONS,
    )
    if err:
        return jsonify(err[0]), err[1]

    filename = request.files["file"].filename or ""

    # The file-count cap needs no extraction, so check it FIRST: a sixth
    # attachment is refused before we pay Google Vision to OCR an image
    # whose text we would immediately discard.
    draft = get_open_draft()
    existing = normalise_context_files(draft.context_files if draft else [])
    # #336: capacity is measured across BOTH stores. The prompt ceiling
    # doesn't care which one a document came from, so checking only this
    # reflection's share would let a sixth file through and blow the
    # budget at analysis time, when it is too late to say so.
    full = check_capacity(merged_context_files(existing))
    if full:
        return jsonify({"error": full}), 422

    try:
        attachment = build_attachment(filename, file_bytes)
    except ContextExtractionError as e:
        # Log the shape of the failure, never the filename or content.
        logger.info(
            "reflection attachment rejected (%d bytes): %s",
            len(file_bytes), e,
        )
        return jsonify({"error": str(e)}), e.status
    except Exception:
        logger.exception("reflection attachment extraction crashed")
        return jsonify({"error": "Couldn't read that file."}), 500

    capacity_error = check_capacity(
        merged_context_files(existing), attachment["chars"],
    )
    if capacity_error:
        return jsonify({"error": capacity_error}), 422

    draft = save_draft(
        transcript=(draft.transcript if draft else "") or "",
        raw_segments=(draft.raw_segments if draft else None),
        context_files=[*existing, attachment],
    )
    payload = _attachment_payload(draft)
    payload["attachment"] = {
        k: v for k, v in attachment.items() if k != "text"
    }
    return jsonify(payload), 201


# --- Always-attached documents (#336) ---------------------------------------
# #328 files a document against the open DRAFT, so it follows one
# reflection and retires with it. Reflecting toward a fixed date across
# many sittings then means re-uploading the same job description and the
# same 90-day plan every time. A document marked always-attached lives in
# its own table and rides along with every analysis.
#
# The two stores share ONE budget: marking something global must not
# quietly buy extra room in the prompt.


@bp.get("/global-context")
@login_required
def list_global_context(email: str):  # noqa: ARG001
    """Every always-attached document. Metadata only — never the text."""
    return jsonify(_global_payload())


@bp.post("/global-context")
@login_required
@limiter.limit(PAID_API)  # paid: image uploads hit Google Vision OCR
def add_global_context(email: str):  # noqa: ARG001
    """Upload a document that should ride along with EVERY reflection.

    Same extraction, validation and truncation path as the per-session
    route above — only where the extracted text is filed differs. The
    FILE itself is still never stored (#328 / ADR-037).

    Capacity is checked against the MERGED list (globals + whatever is on
    the open draft), because the prompt ceiling doesn't care which store
    a document came from.
    """
    file_bytes, _ct, err = validate_upload(
        request,
        field_name="file",
        max_bytes=MAX_UPLOAD_BYTES,
        allowed_extensions=ALLOWED_EXTENSIONS,
    )
    if err:
        return jsonify(err[0]), err[1]
    filename = request.files["file"].filename or ""

    draft = get_open_draft()
    merged = merged_context_files(draft.context_files if draft else [])
    # File-count check first — a sixth document is refused before paying
    # Google Vision to OCR an image whose text we would then discard.
    full = check_capacity(merged)
    if full:
        return jsonify({"error": full}), 422

    try:
        attachment = build_attachment(filename, file_bytes)
    except ContextExtractionError as e:
        logger.info(
            "global context file rejected (%d bytes): %s", len(file_bytes), e,
        )
        return jsonify({"error": str(e)}), e.status
    except Exception:
        logger.exception("global context extraction crashed")
        return jsonify({"error": "Couldn't read that file."}), 500

    capacity_error = check_capacity(merged, attachment["chars"])
    if capacity_error:
        return jsonify({"error": capacity_error}), 422

    record = add_global_file(attachment)
    payload = _global_payload()
    payload["attachment"] = {k: v for k, v in record.items() if k != "text"}
    return jsonify(payload), 201


@bp.post("/attachment/<attachment_id>/make-global")
@login_required
def make_attachment_global(email: str, attachment_id: str):  # noqa: ARG001
    """MOVE one of this reflection's attachments into the global store.

    The natural moment to decide a document is permanent is after having
    attached it once — "I'll want this every week" is a thought that
    arrives second, not first. Re-uploading to change its filing would be
    a second Vision call for bytes the server already turned into text.

    A move, not a copy: leaving it in both stores would show the user the
    same document twice and, but for the de-duplication in
    ``merged_context_files``, charge the shared budget twice.

    Free — the text already exists, so no extraction and no paid call.
    """
    draft = get_open_draft()
    if draft is None:
        return jsonify({"error": "No reflection in progress."}), 404
    existing = normalise_context_files(draft.context_files)
    match = next((f for f in existing if f["id"] == attachment_id), None)
    if match is None:
        return jsonify({"error": "That attachment is no longer here."}), 404

    record = add_global_file(match)
    draft = save_draft(
        transcript=draft.transcript or "",
        raw_segments=draft.raw_segments,
        context_files=[f for f in existing if f["id"] != attachment_id],
    )
    payload = _attachment_payload(draft)
    payload["global"] = _global_payload()["files"]
    payload["moved"] = {k: v for k, v in record.items() if k != "text"}
    return jsonify(payload), 200


@bp.delete("/global-context/<file_id>")
@login_required
def delete_global_context(email: str, file_id: str):  # noqa: ARG001
    """Stop a document riding along with every reflection. Idempotent.

    A hard delete. Reflections it already informed are untouched — they
    keep their own transcripts and their own attachments.
    """
    remove_global_file(file_id)
    return jsonify(_global_payload()), 200


@bp.delete("/attachment/<attachment_id>")
@login_required
def remove_attachment(email: str, attachment_id: str):  # noqa: ARG001
    """Detach one context document from the open draft. Idempotent."""
    draft = get_open_draft()
    if draft is None:
        return jsonify(_attachment_payload(None)), 200
    existing = normalise_context_files(draft.context_files)
    remaining = [f for f in existing if f["id"] != attachment_id]
    if len(remaining) != len(existing):
        draft = save_draft(
            transcript=draft.transcript or "",
            raw_segments=draft.raw_segments,
            context_files=remaining,
        )
    return jsonify(_attachment_payload(draft)), 200


# --- Milestone: the runway the reflection counts down to (#325) -------------
# Free endpoints (no paid API). The milestone feeds BOTH the /reflection
# header and the Claude prompt, so proposals get sequenced against a real
# date instead of floating free.


@bp.get("/milestone")
@login_required
def get_milestone_route(email: str):  # noqa: ARG001
    """The resolved milestone (may be unconfigured)."""
    return jsonify(get_milestone())


@bp.put("/milestone")
@login_required
@validate_json_body
def put_milestone(email: str):  # noqa: ARG001
    """Set the milestone.

    Body: ``{"label": "...", "target_date": "YYYY-MM-DD", "goal_id": "..."}``.
    ``goal_id`` links the name to a goal (the label then follows that
    goal's title); omit it to use the typed ``label``.
    """
    data = g.json_body
    try:
        milestone = set_milestone(
            label=data.get("label"),
            target_date=data.get("target_date"),
            goal_id=data.get("goal_id") or None,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    return jsonify(milestone), 200


@bp.delete("/milestone")
@login_required
def delete_milestone(email: str):  # noqa: ARG001
    """Clear the milestone. Idempotent."""
    clear_milestone()
    return "", 204


@bp.get("")
@login_required
def list_all(email: str):  # noqa: ARG001
    """List past reflections (newest first) for the history view.

    #238 (2026-05-26): supports two query flags:
      ``?include_archived=true``  — also include rows where
          ``is_archived=True``. Default off; UI sends when the
          Show-archived toggle is on.
      ``?include_deleted=true``   — also include rows where
          ``is_active=False`` (soft-deleted). Default off; UI sends
          ONLY when loading the Recently-deleted section.

    Truthy values: ``true``, ``1``, ``yes`` (case-insensitive).
    """
    def _truthy(s):
        return (s or "").strip().lower() in ("true", "1", "yes")

    include_archived = _truthy(request.args.get("include_archived"))
    include_deleted = _truthy(request.args.get("include_deleted"))
    reflections = list_reflections(
        include_archived=include_archived,
        include_deleted=include_deleted,
    )
    return jsonify({
        "reflections": [_serialize(r) for r in reflections],
    })


# #238 (2026-05-26): archive + soft-delete endpoints.


@bp.post("/draft/analyze")
@login_required
@limiter.limit(PAID_API)  # paid: a full Claude analysis per click
def analyze_draft(email: str):  # noqa: ARG001
    """Analyse the OPEN DRAFT without ending the reflection (#333).

    `submit` is a one-way door: it commits a Reflection row, hard-deletes
    the draft and leaves the user on the review screen with no way back
    into the same session. A user reflecting for hours wants proposals
    PART WAY through — review, apply some, keep dictating.

    So this analyses the draft in place. Nothing is committed as a
    finished reflection, the draft (text, raw_segments, attachments)
    survives untouched, and the proposals land on the draft row so the
    existing confirm endpoint can apply them by draft id.

    A fresh pass SUPERSEDES the previous one: `applied_at` /
    `applied_actions` are cleared so the user can apply again after
    adding more. Anything applied in an earlier pass already exists as
    real rows and stays undoable through the recycle bin — the draft's
    audit fields are session scaffolding, not the ledger.
    """
    draft = get_open_draft()
    if draft is None:
        return jsonify({"error": "No reflection in progress."}), 404
    if not (draft.transcript or "").strip():
        return jsonify({"error": "Write or say something first."}), 422

    # #336: always-attached documents come along here too — a checkpoint
    # reading less than the final analysis would propose against a
    # different picture and quietly confuse the comparison.
    context_files = merged_context_files(draft.context_files)
    try:
        analysis = analyze_reflection(
            draft.transcript,
            exclude_id=draft.id,
            context_files=context_files,
            # #334: a checkpoint on a CONTINUED reflection still needs to
            # say what was carried over — otherwise the interim pass reads
            # the parent's paragraphs as today's words.
            continued_from=draft.continued_from,
        )
    except RuntimeError as e:
        logger.warning("Interim analysis failed (draft %s kept): %s", draft.id, e)
        return jsonify({"error": f"Analysis failed: {e}", "saved": True}), 422
    except Exception:
        logger.exception("Interim analysis crashed (draft %s kept)", draft.id)
        return jsonify({"error": "Analysis failed (unexpected)", "saved": True}), 500

    draft = attach_analysis(
        draft,
        proposed={
            "explicit": analysis["explicit"],
            "suggested": analysis["suggested"],
        },
        ai_cost_usd=analysis["ai_cost_usd"],
    )
    reset_applied_state(draft)
    payload = _serialize(draft)
    # Tells the client this review is a checkpoint, not the end: the
    # review screen then offers "Back to writing" instead of Start Over.
    payload["interim"] = True
    return jsonify(payload)


@bp.patch("/<uuid:reflection_id>")
@login_required
@validate_json_body
def rename(email: str, reflection_id):  # noqa: ARG001
    """Give a reflection a name, or clear it (#339).

    History rows were labelled `iso_week - date - input_mode`, which is
    byte-identical for two reflections written on the same day in the
    same mode — a user could not tell a throwaway test apart from a real
    multi-hour session. A name is the user's own words for what the
    sitting was about, and it also rides into the continuity prompt so
    Claude can refer back to it.

    PATCH (not GET) because it mutates — see #190. Sending an empty or
    whitespace-only title CLEARS the name rather than storing "", so the
    generated fallback label applies again.
    """
    title = g.json_body.get("title")
    if title is not None and not isinstance(title, str):
        return jsonify({"error": "title must be a string"}), 422
    reflection = set_reflection_title(reflection_id, title)
    if reflection is None:
        return jsonify({"error": "Reflection not found"}), 404
    return jsonify(_serialize(reflection))


@bp.post("/<uuid:reflection_id>/analyze")
@login_required
@limiter.limit(PAID_API)  # paid: a full Claude analysis per click
def reanalyze(email: str, reflection_id):  # noqa: ARG001
    """Re-run Claude over an ALREADY-SAVED reflection (#338).

    The error state has always told the user a failed analysis "can be
    re-analyzed later" — and until now nothing could. The transcript is
    persisted before the Claude call (see ``submit``), so a timeout or a
    transient API error left the reflection saved forever and analysable
    never. A real multi-hour reflection was stranded this way on
    2026-09-24 by the 60s timeout fixed in #337.

    Re-analysis uses the reflection's OWN stored transcript and
    ``context_files``, so the attached documents are read again exactly
    as they were on the first attempt. ``exclude_id`` keeps the
    reflection out of its own continuity context, same as ``submit``.

    Any previous ``proposed_actions`` are replaced: the user is asking
    for a fresh read of the same words, and keeping a stale failed-run
    remnant alongside would make the review screen ambiguous.

    #335: a SYNTHESIS row is re-analysed by re-reading the sittings it
    was built from, not its own transcript — that is a one-line header
    naming them, and running Claude over it would produce a confident
    analysis of a list of dates. Sources that have since gone are simply
    dropped; a look-back over the four that remain beats an error about
    the fifth.
    """
    reflection = get_reflection(reflection_id)
    if reflection is None:
        return jsonify({"error": "Reflection not found"}), 404
    if not (reflection.transcript or "").strip():
        return jsonify({"error": "That reflection has no transcript to analyze."}), 422

    sources = synthesis_sources_of(reflection)  # [] for an ordinary row
    shortened: list[str] = []
    if sources:
        transcript, shortened = combined_transcript(sources)
        context_files = merged_context_files(merged_source_files(sources))
    else:
        transcript = reflection.transcript
        context_files = merged_context_files(reflection.context_files)

    try:
        analysis = analyze_reflection(
            transcript,
            exclude_id=reflection.id,
            context_files=context_files,
            continued_from=reflection.continued_from,  # #334
            synthesis_sources=sources or None,  # #335
            shortened=shortened,
        )
    except RuntimeError as e:
        logger.warning("Re-analysis failed for reflection %s: %s", reflection.id, e)
        return jsonify({"error": f"Analysis failed: {e}", "saved": True}), 422
    except Exception:
        logger.exception("Re-analysis crashed for reflection %s", reflection.id)
        return jsonify({"error": "Analysis failed (unexpected)", "saved": True}), 500

    reflection = attach_analysis(
        reflection,
        proposed={
            "explicit": analysis["explicit"],
            "suggested": analysis["suggested"],
        },
        ai_cost_usd=analysis["ai_cost_usd"],
    )
    return jsonify(_serialize(reflection))


@bp.post("/analyze-together")
@login_required
@limiter.limit(PAID_API)  # paid: one Claude call over several transcripts
@validate_json_body
def analyze_together(email: str):  # noqa: ARG001
    """Read several past reflections in ONE analysis (#335).

    A single sitting can say what happened that week. It cannot answer
    "you have mentioned the handover three weeks running and still have
    no task for it" — that only has an answer across sittings, and it is
    the question a multi-week run-up to a start date actually needs.

    The continuity block (#325) already carries the previous three
    reflections, but truncated to 1200 characters each: background, not
    material to reason over. This passes the selected transcripts in
    FULL, plus the de-duplicated union of their attached documents, and
    reframes the prompt as a look-back rather than a new week's entry.

    Like #334 it creates a NEW row and modifies none of the sources. The
    row exists because ``confirm`` applies actions BY reflection id, so
    proposals need somewhere to live — and because the look-back is
    itself worth keeping. Its own transcript is a short header naming the
    sittings; their words stay on the rows they belong to.

    Body: ``{"ids": ["<uuid>", ...]}`` — 2 to MAX_COMBINED of them.

    Status codes:
      201 — analysed; body is the new row plus ``combined: true``
      422 — bad selection (too few/many, unknown id), or Claude failed
            AFTER the row was saved (``saved: true``, re-analyzable)
    """
    ids = g.json_body.get("ids")
    try:
        sources = resolve_combined_sources(ids)
    except CombinedSelectionError as e:
        return jsonify({"error": str(e)}), 422

    transcript, shortened = combined_transcript(sources)
    # #336: the always-attached store on top of the union across sources.
    context_files = merged_context_files(merged_source_files(sources))

    # Persist BEFORE the paid call, same order and same reason as
    # ``submit``: a timeout must not throw away a row the user can
    # re-analyze from their history (#338).
    synthesis = create_synthesis(sources, shortened)

    try:
        analysis = analyze_reflection(
            transcript,
            exclude_id=synthesis.id,
            context_files=context_files,
            synthesis_sources=sources,
            shortened=shortened,
        )
    except RuntimeError as e:
        logger.warning(
            "Combined analysis failed (synthesis %s saved): %s",
            synthesis.id, e,
        )
        return jsonify({
            "error": f"Analysis failed: {e}",
            "reflection_id": str(synthesis.id),
            "saved": True,
        }), 422
    except Exception:
        logger.exception(
            "Combined analysis crashed (synthesis %s saved)", synthesis.id,
        )
        return jsonify({
            "error": "Analysis failed (unexpected)",
            "reflection_id": str(synthesis.id),
            "saved": True,
        }), 500

    synthesis = attach_analysis(
        synthesis,
        proposed={
            "explicit": analysis["explicit"],
            "suggested": analysis["suggested"],
        },
        ai_cost_usd=analysis["ai_cost_usd"],
    )
    payload = _serialize(synthesis)
    # Tells the review screen to say what it is reading, and how many
    # sittings went in — a proposal list with no such framing looks like
    # it came from whichever reflection was open.
    payload["combined"] = True
    payload["source_count"] = len(sources)
    payload["shortened"] = shortened
    return jsonify(payload), 201


@bp.post("/<uuid:reflection_id>/continue")
@login_required
def continue_past(email: str, reflection_id):  # noqa: ARG001
    """Continue a past reflection by FORKING it into a new draft (#334).

    Reflecting toward a date weeks out spans many sittings, and every
    submit used to be terminal: the next sitting started from an empty
    box, with the earlier thinking reachable only as the 1200-char
    snippet the continuity block carries.

    This seeds a NEW draft from the saved sitting — its text, its voice
    segments and (critically) its attached documents — and links back via
    ``continued_from_id``. **The saved reflection is not modified.** The
    alternative, re-opening and appending to the original row, was
    rejected deliberately: it would rewrite what the user thought on a
    given day, and both this page and the Help page promise every
    reflection is kept forever.

    Not rate-limited under ``PAID_API``: this is a pure DB copy. No
    Whisper, no Claude — the cost arrives later, when the user analyses.

    Status codes:
      200 — forked; body is ``{"draft": {...}}``
      404 — no such reflection, or it is a draft / soft-deleted
      409 — a draft with content is already open (refused, never merged)
    """
    try:
        draft = continue_reflection(reflection_id)
    except DraftAlreadyOpen as e:
        return jsonify({"error": str(e)}), 409
    if draft is None:
        return jsonify({"error": "Reflection not found"}), 404
    logger.info(
        "reflection %s continued as draft %s", reflection_id, draft.id
    )
    return jsonify({"draft": _serialize(draft)}), 200


@bp.post("/<uuid:reflection_id>/archive")
@login_required
def archive(email: str, reflection_id):  # noqa: ARG001
    """Mark a reflection archived (hide from default history)."""
    from reflection_service import set_reflection_archived
    r = set_reflection_archived(reflection_id, archived=True)
    if r is None:
        return jsonify({"error": "Reflection not found"}), 404
    return jsonify(_serialize(r))


@bp.post("/<uuid:reflection_id>/unarchive")
@login_required
def unarchive(email: str, reflection_id):  # noqa: ARG001
    """Restore a reflection from the archive."""
    from reflection_service import set_reflection_archived
    r = set_reflection_archived(reflection_id, archived=False)
    if r is None:
        return jsonify({"error": "Reflection not found"}), 404
    return jsonify(_serialize(r))


@bp.delete("/<uuid:reflection_id>")
@login_required
def delete(email: str, reflection_id):  # noqa: ARG001
    """Soft-delete a reflection. The row stays in the DB; the
    Recently-deleted UI surfaces it for restore."""
    from reflection_service import soft_delete_reflection
    r = soft_delete_reflection(reflection_id)
    if r is None:
        return jsonify({"error": "Reflection not found"}), 404
    return jsonify(_serialize(r))


@bp.post("/<uuid:reflection_id>/restore")
@login_required
def restore(email: str, reflection_id):  # noqa: ARG001
    """Restore a soft-deleted reflection back into the history list."""
    from reflection_service import restore_reflection
    r = restore_reflection(reflection_id)
    if r is None:
        return jsonify({"error": "Reflection not found"}), 404
    return jsonify(_serialize(r))


@bp.get("/<uuid:reflection_id>")
@login_required
def detail(email: str, reflection_id):  # noqa: ARG001
    """One reflection with its transcript + proposed/applied actions."""
    reflection = get_reflection(reflection_id)
    if reflection is None:
        return jsonify({"error": "Reflection not found"}), 404
    return jsonify(_serialize(reflection))
