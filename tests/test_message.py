"""Tests for cota.message.message.Message"""

from cota.message.message import Message


class TestMessage:

    def test_default_sender(self):
        msg = Message(text="hello")
        assert msg.sender == "user"
        assert msg.sender_id == "default_user"

    def test_custom_sender(self):
        msg = Message(sender="bot", sender_id="bot1", text="hi")
        assert msg.sender == "bot"
        assert msg.sender_id == "bot1"

    def test_receiver_defaults(self):
        msg = Message(receiver="bot", text="hi")
        assert msg.receiver == "bot"
        assert msg.receiver_id == "default_bot"

    def test_receiver_none(self):
        msg = Message(text="hi")
        assert msg.receiver is None
        assert msg.receiver_id is None

    def test_session_id_auto_generated(self):
        msg = Message(text="hi")
        assert msg.session_id is not None
        assert len(msg.session_id) == 32  # uuid hex

    def test_session_id_explicit(self):
        msg = Message(text="hi", session_id="sess_123")
        assert msg.session_id == "sess_123"

    def test_text_strip(self):
        msg = Message(text="  hello world  ")
        assert msg.text == "hello world"

    def test_text_none(self):
        msg = Message()
        assert msg.text is None

    def test_as_dict(self):
        msg = Message(
            sender="user",
            sender_id="u1",
            receiver="bot",
            receiver_id="b1",
            session_id="s1",
            text="test",
            metadata={"key": "value"},
        )
        d = msg.as_dict()
        assert d["sender"] == "user"
        assert d["sender_id"] == "u1"
        assert d["receiver"] == "bot"
        assert d["receiver_id"] == "b1"
        assert d["session_id"] == "s1"
        assert d["text"] == "test"
        assert d["metadata"] == {"key": "value"}

    def test_sender_id_defaults_for_bot(self):
        msg = Message(sender="bot", text="hi")
        assert msg.sender_id == "default_bot"
