"""Tests for clinical notes — encryption, authorization, cross-patient isolation."""

import pytest
from app.models.user import User
from app.models.clinical_note import ClinicalNote
from app.extensions import db
from tests.signing_helpers import signed_data


def _create_user(app, username, role="patient", password="Password1"):
    with app.app_context():
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, username, password="Password1"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Encryption at rest
# ---------------------------------------------------------------------------

def test_note_content_encrypted_in_db(app):
    """content_encrypted must not equal the plaintext note."""
    with app.app_context():
        note = ClinicalNote.create(
            patient_id=1, author_id=1, content="Sensitive clinical finding"
        )
        assert note.content_encrypted != "Sensitive clinical finding"
        assert "Sensitive" not in note.content_encrypted


def test_note_decrypts_correctly(app):
    """content property must return the original plaintext."""
    with app.app_context():
        note = ClinicalNote.create(
            patient_id=1, author_id=1, content="Blood pressure normal"
        )
        assert note.content == "Blood pressure normal"


def test_note_stored_encrypted_not_plaintext(app):
    """After persisting to DB, the raw column value is ciphertext."""
    uid = _create_user(app, "clinician_enc", role="clinician")
    pid = _create_user(app, "patient_enc")
    with app.app_context():
        note = ClinicalNote.create(
            patient_id=pid, author_id=uid, content="My secret note"
        )
        db.session.add(note)
        db.session.commit()
        nid = note.id

    with app.app_context():
        from app.extensions import db as _db
        raw = _db.session.execute(
            _db.text("SELECT content_encrypted FROM clinical_notes WHERE id = :id"),
            {"id": nid},
        ).fetchone()[0]
        assert "My secret note" not in raw


# ---------------------------------------------------------------------------
# Staff can create and read notes
# ---------------------------------------------------------------------------

def test_clinician_can_create_note(client, app):
    cid = _create_user(app, "clinician_cr", role="clinician")
    pid = _create_user(app, "patient_cr")
    _login(client, "clinician_cr")

    path = f"/notes/patient/{pid}"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"content": "Routine checkup note"}),
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        note = ClinicalNote.query.filter_by(patient_id=pid).first()
        assert note is not None
        assert note.content == "Routine checkup note"


def test_admin_can_create_note(client, app):
    _create_user(app, "admin_note", role="administrator")
    pid = _create_user(app, "patient_adm")
    _login(client, "admin_note")

    path = f"/notes/patient/{pid}"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"content": "Admin observation"}),
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        note = ClinicalNote.query.filter_by(patient_id=pid).first()
        assert note is not None


def test_staff_can_read_patient_notes(client, app):
    cid = _create_user(app, "clinician_rd", role="clinician")
    pid = _create_user(app, "patient_rd")

    with app.app_context():
        note = ClinicalNote.create(patient_id=pid, author_id=cid, content="Lab results normal")
        db.session.add(note)
        db.session.commit()

    _login(client, "clinician_rd")
    resp = client.get(f"/notes/patient/{pid}")
    assert resp.status_code == 200
    assert b"Lab results normal" in resp.data


# ---------------------------------------------------------------------------
# Patient reads own notes only
# ---------------------------------------------------------------------------

def test_patient_can_read_own_notes(client, app):
    cid = _create_user(app, "clinician_pat", role="clinician")
    pid = _create_user(app, "patient_own")

    with app.app_context():
        note = ClinicalNote.create(patient_id=pid, author_id=cid, content="Patient own note text")
        db.session.add(note)
        db.session.commit()

    _login(client, "patient_own")
    resp = client.get("/notes/my")
    assert resp.status_code == 200
    assert b"Patient own note text" in resp.data


def test_patient_cannot_access_staff_notes_route(client, app):
    pid1 = _create_user(app, "patient_x1")
    pid2 = _create_user(app, "patient_x2")
    _login(client, "patient_x1")

    resp = client.get(f"/notes/patient/{pid2}")
    assert resp.status_code == 403


def test_patient_my_notes_no_cross_leak(client, app):
    """A patient's /notes/my must not show another patient's notes."""
    cid = _create_user(app, "clinician_iso", role="clinician")
    pid1 = _create_user(app, "patient_iso1")
    pid2 = _create_user(app, "patient_iso2")

    with app.app_context():
        note_for_2 = ClinicalNote.create(
            patient_id=pid2, author_id=cid, content="Private note for patient 2"
        )
        db.session.add(note_for_2)
        db.session.commit()

    _login(client, "patient_iso1")
    resp = client.get("/notes/my")
    assert resp.status_code == 200
    assert b"Private note for patient 2" not in resp.data


# ---------------------------------------------------------------------------
# Authorization: patient cannot create notes
# ---------------------------------------------------------------------------

def test_patient_cannot_post_note(client, app):
    pid = _create_user(app, "patient_nopost")
    _login(client, "patient_nopost")

    path = f"/notes/patient/{pid}"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"content": "Self-written note"}),
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_unauthenticated_cannot_read_notes(client, app):
    resp = client.get("/notes/my")
    assert resp.status_code in (302, 401)
