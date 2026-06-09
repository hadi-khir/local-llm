from app.storage import Storage, build_conversation_title


def test_storage_round_trip(tmp_path) -> None:
    storage = Storage(tmp_path / "app.db")
    storage.initialize()
    conversation_id = storage.create_conversation("Hello")
    storage.add_message(conversation_id, "user", "Hi")
    storage.add_message(conversation_id, "assistant", "Hello there")

    conversations = storage.list_conversations()
    messages = storage.get_messages(conversation_id)

    assert conversations[0]["title"] == "Hello"
    assert [message["role"] for message in messages] == ["user", "assistant"]


def test_build_conversation_title_truncates() -> None:
    title = build_conversation_title("word " * 30, max_length=24)
    assert len(title) <= 24
    assert title.endswith("…")
