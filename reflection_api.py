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
    POST   /api/reflection/<id>/confirm          — apply the user-selected
        actions; returns an apply summary
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
"""
from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request

from auth import login_required
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
    analyze_reflection,
    apply_selected_actions,
    attach_analysis,
    discard_draft,
    get_open_draft,
    get_reflection,
    list_reflections,
    save_draft,
    save_reflection,
    set_reflection_title,
)
from utils import validate_json_body, validate_upload
from voice_service import (
    ALLOWED_AUDIO_TYPES,
    WHISPER_MAX_UPLOAD_BYTES,
    transcribe_audio,
)

logger = logging.getLogger(__name__)

bp = Blueprint("reflection_api", __name__, url_prefix="/api/reflection")


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
            context_files=context_files,
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
    return {
        "context_files": public_view(files),
        "total_chars": total_chars(files),
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
    full = check_capacity(existing)
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

    capacity_error = check_capacity(existing, attachment["chars"])
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
    """
    reflection = get_reflection(reflection_id)
    if reflection is None:
        return jsonify({"error": "Reflection not found"}), 404
    if not (reflection.transcript or "").strip():
        return jsonify({"error": "That reflection has no transcript to analyze."}), 422

    context_files = normalise_context_files(reflection.context_files)
    try:
        analysis = analyze_reflection(
            reflection.transcript,
            exclude_id=reflection.id,
            context_files=context_files,
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
