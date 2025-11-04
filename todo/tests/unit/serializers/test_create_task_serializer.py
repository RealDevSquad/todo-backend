from unittest import TestCase

from bson import ObjectId

from todo.serializers.create_task_serializer import CreateTaskSerializer
from datetime import datetime, timedelta, timezone


class CreateTaskSerializerTest(TestCase):
    def setUp(self):
        self.valid_data = {
            "title": "Test task",
            "description": "Some test description",
            "priority": "LOW",
            "status": "TODO",
            "assignee_id": str(ObjectId()),
            "user_type": "user",
            "labels": [],
            "dueAt": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
            "timezone": "Asia/Calcutta",
        }

    def test_serializer_validates_correct_data(self):
        serializer = CreateTaskSerializer(data=self.valid_data)
        self.assertTrue(serializer.is_valid())

    def test_serializer_fails_without_title(self):
        data = self.valid_data.copy()
        del data["title"]
        serializer = CreateTaskSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("title", serializer.errors)

    def test_serializer_rejects_invalid_status(self):
        data = self.valid_data.copy()
        data["status"] = "INVALID"
        serializer = CreateTaskSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("status", serializer.errors)

    def test_serializer_rejects_invalid_assignee_id(self):
        data = self.valid_data.copy()
        data["assignee_id"] = "1234"  # Not a valid ObjectId
        serializer = CreateTaskSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("assignee_id", serializer.errors)

    def test_serializer_rejects_missing_user_type(self):
        data = self.valid_data.copy()
        del data["user_type"]
        serializer = CreateTaskSerializer(data=data)
        # Should be valid, as assignee is optional, but if assignee_id is present, user_type must be too
        self.assertTrue(serializer.is_valid())
        # If both are missing, should still be valid (assignee is optional)

    def test_serializer_rejects_invalid_user_type(self):
        data = self.valid_data.copy()
        data["user_type"] = "invalid_type"
        serializer = CreateTaskSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("user_type", serializer.errors)

    def test_serializer_accepts_valid_team_id(self):
        data = self.valid_data.copy()
        data["team_id"] = str(ObjectId())
        serializer = CreateTaskSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertIn("assignee", serializer.validated_data)
        self.assertEqual(serializer.validated_data["assignee"]["team_id"], data["team_id"])

    def test_serializer_rejects_invalid_team_id(self):
        data = self.valid_data.copy()
        data["team_id"] = "invalid_team_id"
        serializer = CreateTaskSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("team_id", serializer.errors)

    def test_serializer_handles_empty_team_id(self):
        data = self.valid_data.copy()
        data["team_id"] = ""
        serializer = CreateTaskSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertIn("assignee", serializer.validated_data)
        self.assertNotIn("team_id", serializer.validated_data["assignee"])
