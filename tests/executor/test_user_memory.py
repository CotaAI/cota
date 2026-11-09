"""Tests for cota.executor.user_memory — MemoryUserMemory"""

import pytest
from cota.executor.user_memory import MemoryUserMemory


@pytest.fixture
def user_memory():
    return MemoryUserMemory()


class TestMemoryUserMemory:

    def test_set_and_get(self, user_memory):
        user_memory.set("user1", "theme", "dark")
        value = user_memory.get("user1", "theme")
        assert value == "dark"

    def test_get_nonexistent_key(self, user_memory):
        value = user_memory.get("user1", "nonexistent")
        assert value is None

    def test_get_nonexistent_user(self, user_memory):
        value = user_memory.get("nobody", "key")
        assert value is None

    def test_delete(self, user_memory):
        user_memory.set("user1", "key", "value")
        deleted = user_memory.delete("user1", "key")
        assert deleted is True
        value = user_memory.get("user1", "key")
        assert value is None

    def test_delete_nonexistent(self, user_memory):
        deleted = user_memory.delete("user1", "nope")
        assert deleted is False

    def test_get_all(self, user_memory):
        user_memory.set("user1", "a", "1")
        user_memory.set("user1", "b", "2")
        all_data = user_memory.get_all("user1")
        assert all_data == {"a": "1", "b": "2"}

    def test_get_all_empty_user(self, user_memory):
        all_data = user_memory.get_all("nobody")
        assert all_data == {}

    def test_get_all_returns_copy(self, user_memory):
        user_memory.set("user1", "k", "v")
        data = user_memory.get_all("user1")
        data["k"] = "modified"
        assert user_memory.get("user1", "k") == "v"

    def test_user_isolation(self, user_memory):
        user_memory.set("user1", "key", "val1")
        user_memory.set("user2", "key", "val2")
        assert user_memory.get("user1", "key") == "val1"
        assert user_memory.get("user2", "key") == "val2"

    def test_overwrite(self, user_memory):
        user_memory.set("user1", "key", "old")
        user_memory.set("user1", "key", "new")
        assert user_memory.get("user1", "key") == "new"

    def test_search(self, user_memory):
        user_memory.set("user1", "favorite_color", "blue")
        user_memory.set("user1", "theme", "dark_blue")
        user_memory.set("user1", "timezone", "UTC")

        results = user_memory.search("user1", "blue")
        assert "favorite_color" in results
        assert "theme" in results
        assert "timezone" not in results

    def test_search_case_insensitive(self, user_memory):
        user_memory.set("user1", "Name", "Alice")
        results = user_memory.search("user1", "alice")
        assert "Name" in results

    def test_search_no_match(self, user_memory):
        user_memory.set("user1", "key", "value")
        results = user_memory.search("user1", "xyz")
        assert results == {}

    def test_complex_values(self, user_memory):
        user_memory.set("user1", "prefs", {"lang": "zh", "style": "formal"})
        result = user_memory.get("user1", "prefs")
        assert result == {"lang": "zh", "style": "formal"}
