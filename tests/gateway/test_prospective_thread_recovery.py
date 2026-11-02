"""Durable Discord auto-thread recovery regressions for #147943."""

from dataclasses import replace
from datetime import datetime

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.session import SessionSource, SessionStore, build_session_key


def _source(**kwargs):
    return SessionSource(
        platform=Platform.DISCORD, chat_id="channel", chat_type="channel",
        user_id="user", **kwargs,
    )


@pytest.mark.parametrize("previous_thread", [None, "older-thread"])
def test_new_prospective_thread_does_not_adopt_an_older_peer(tmp_path, previous_thread):
    store = SessionStore(tmp_path / "sessions", GatewayConfig(write_sessions_json=False))
    previous = store.get_or_create_session(_source(prospective_thread_id=previous_thread))
    store._db.append_message(previous.session_id, "user", "older conversation")
    incoming = _source(prospective_thread_id="new-thread")

    current = store.get_or_create_session(incoming)

    assert current.session_id != previous.session_id
    assert store._db.get_session(previous.session_id)["session_key"] == previous.session_key
    assert store._db.get_session(current.session_id)["session_key"] == build_session_key(incoming)


def test_prospective_thread_recovers_exact_row_and_real_thread_continues_it(tmp_path):
    config = GatewayConfig(write_sessions_json=False)
    store = SessionStore(tmp_path / "sessions", config)
    source = _source(prospective_thread_id="thread")
    original = store.get_or_create_session(source)
    store._db.append_message(original.session_id, "user", "thread-local marker")

    recovered = store._query_recoverable_session(
        session_key=build_session_key(source), source=source, now=datetime.now(),
    )

    assert recovered is not None and recovered.session_id == original.session_id
    followup = replace(source, chat_type="thread", thread_id="thread", prospective_thread_id=None)
    assert store.get_or_create_session(followup).session_id == original.session_id
    assert store._db.get_messages(original.session_id)[0]["content"] == "thread-local marker"


def test_ordinary_channel_still_recovers_a_peer_with_a_legacy_key(tmp_path):
    store = SessionStore(tmp_path / "sessions", GatewayConfig(write_sessions_json=False))
    source = _source()
    original = store.get_or_create_session(source)
    store._db.append_message(original.session_id, "user", "legacy conversation")
    store._db.record_gateway_session_peer(
        original.session_id, source="discord", session_key="legacy-key",
        chat_id=source.chat_id, chat_type=source.chat_type, user_id=source.user_id,
    )

    recovered = store._query_recoverable_session(
        session_key=build_session_key(source), source=source, now=datetime.now(),
    )

    assert recovered is not None and recovered.session_id == original.session_id
