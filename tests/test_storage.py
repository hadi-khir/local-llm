from app.storage import Storage, build_conversation_title


def test_storage_round_trip(tmp_path) -> None:
    storage = Storage(tmp_path / "app.db")
    storage.initialize()
    conversation_id = storage.create_conversation("Hello")
    storage.add_message(conversation_id, "user", "Hi")
    assistant_id = storage.add_message(
        conversation_id,
        "assistant",
        "",
        status="pending",
    )
    storage.append_message_chunk(assistant_id, "Hello there")
    storage.update_message(assistant_id, status="completed")

    conversations = storage.list_conversations()
    messages = storage.get_messages(conversation_id)

    assert conversations[0]["title"] == "Hello"
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "Hello there"
    assert messages[1]["status"] == "completed"


def test_generation_jobs_are_tracked(tmp_path) -> None:
    storage = Storage(tmp_path / "app.db")
    storage.initialize()
    conversation_id = storage.create_conversation("Tracked")
    user_message_id = storage.add_message(conversation_id, "user", "Hi")
    assistant_message_id = storage.add_message(
        conversation_id,
        "assistant",
        "",
        status="pending",
    )
    storage.create_generation_job(
        "req-1",
        conversation_id,
        user_message_id,
        assistant_message_id,
    )
    storage.update_generation_job("req-1", status="streaming")
    storage.mark_incomplete_generations_failed()

    job = storage.get_generation_job("req-1")
    message = storage.get_message(assistant_message_id)

    assert job is not None
    assert job["status"] == "failed"
    assert message is not None
    assert message["status"] == "failed"


def test_build_conversation_title_truncates() -> None:
    title = build_conversation_title("word " * 30, max_length=24)
    assert len(title) <= 24
    assert title.endswith("…")
