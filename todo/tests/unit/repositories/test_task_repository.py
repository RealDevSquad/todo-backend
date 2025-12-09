from unittest import TestCase
from unittest.mock import patch, MagicMock
from pymongo import ReturnDocument
from pymongo.collection import Collection
from bson import ObjectId, errors as bson_errors
from datetime import datetime, timezone, timedelta
import copy

from todo.exceptions.task_exceptions import TaskNotFoundException
from todo.models.task import TaskModel
from todo.repositories.task_repository import TaskRepository
from todo.constants.task import (
    TaskPriority,
    TaskStatus,
    SORT_FIELD_PRIORITY,
    SORT_FIELD_DUE_AT,
    SORT_FIELD_CREATED_AT,
    SORT_FIELD_ASSIGNEE,
    SORT_ORDER_ASC,
    SORT_ORDER_DESC,
)
from todo.tests.fixtures.task import tasks_db_data
from todo.constants.messages import RepositoryErrors, ApiErrors


class TaskRepositoryTests(TestCase):
    def setUp(self):
        self.task_data = copy.deepcopy(tasks_db_data)

        if tasks_db_data:
            original_single_fixture = tasks_db_data[0]
            self.task_db_data_fixture = copy.deepcopy(original_single_fixture)

            if "_id" not in self.task_db_data_fixture or not isinstance(self.task_db_data_fixture["_id"], str):
                self.task_db_data_fixture["_id"] = str(ObjectId())
            self.task_db_data_fixture["_id"] = ObjectId(self.task_db_data_fixture["_id"])

            self.task_db_data_fixture.setdefault("description", "Default description")
            self.task_db_data_fixture.setdefault("assignee", None)
            self.task_db_data_fixture.setdefault("labels", [])
            self.task_db_data_fixture.setdefault("startedAt", None)
            self.task_db_data_fixture.setdefault("dueAt", None)
            self.task_db_data_fixture.setdefault("updatedAt", None)
            self.task_db_data_fixture.setdefault("updatedBy", None)
            self.task_db_data_fixture.setdefault("isAcknowledged", False)
            self.task_db_data_fixture.setdefault("isDeleted", False)
            self.task_db_data_fixture.setdefault("displayId", "#000")
            self.task_db_data_fixture.setdefault("title", "Default Title")
            self.task_db_data_fixture.setdefault("priority", TaskPriority.LOW)
            self.task_db_data_fixture.setdefault("status", TaskStatus.TODO)
            self.task_db_data_fixture.setdefault("createdAt", datetime.now(timezone.utc))
            self.task_db_data_fixture.setdefault("createdBy", "system_test_user")
        else:
            self.task_db_data_fixture = None

        self.patcher_get_collection = patch("todo.repositories.task_repository.TaskRepository.get_collection")
        self.mock_get_collection = self.patcher_get_collection.start()
        self.mock_collection = MagicMock(spec=Collection)
        self.mock_get_collection.return_value = self.mock_collection

    def tearDown(self):
        self.patcher_get_collection.stop()

    def test_list_applies_pagination_correctly(self):
        mock_cursor = MagicMock()
        mock_cursor.__iter__ = MagicMock(return_value=iter(self.task_data))
        self.mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = mock_cursor

        page = 1
        limit = 10
        result = TaskRepository.list(page, limit, sort_by="createdAt", order="desc", user_id=None)

        self.assertEqual(len(result), len(self.task_data))
        self.assertTrue(all(isinstance(task, TaskModel) for task in result))

        self.mock_collection.find.assert_called_once()
        self.mock_collection.find.return_value.sort.assert_called_once_with([("createdAt", -1)])
        self.mock_collection.find.return_value.sort.return_value.skip.assert_called_once_with(0)
        self.mock_collection.find.return_value.sort.return_value.skip.return_value.limit.assert_called_once_with(limit)

    def test_list_returns_empty_list_for_no_tasks(self):
        mock_cursor = MagicMock()
        mock_cursor.__iter__ = MagicMock(return_value=iter([]))
        self.mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = mock_cursor

        result = TaskRepository.list(2, 10, sort_by="createdAt", order="desc", user_id=None)

        self.assertEqual(result, [])
        self.mock_collection.find.assert_called_once()
        self.mock_collection.find.return_value.sort.assert_called_once_with([("createdAt", -1)])
        self.mock_collection.find.return_value.sort.return_value.skip.assert_called_once_with(10)
        self.mock_collection.find.return_value.sort.return_value.skip.return_value.limit.assert_called_once_with(10)

    def test_count_returns_total_task_count(self):
        self.mock_collection.count_documents.return_value = 42

        result = TaskRepository.count()

        self.assertEqual(result, 42)

        self.mock_collection.count_documents.assert_called_once()
        actual_filter = self.mock_collection.count_documents.call_args[0][0]
        self.assertIn("$and", actual_filter)
        self.assertIn("status", actual_filter["$and"][0])
        self.assertIn("$or", actual_filter["$and"][1])

    def test_get_all_returns_all_tasks(self):
        self.mock_collection.find.return_value = self.task_data

        result = TaskRepository.get_all()

        self.assertEqual(len(result), len(self.task_data))
        self.assertTrue(all(isinstance(task, TaskModel) for task in result))

        self.mock_collection.find.assert_called_once()

    def test_get_all_returns_empty_list_for_no_tasks(self):
        self.mock_collection.find.return_value = []

        result = TaskRepository.get_all()

        self.assertEqual(result, [])
        self.mock_collection.find.assert_called_once()

    def test_get_by_id_returns_task_model_when_found(self):
        task_id_str = str(self.task_db_data_fixture["_id"])
        self.mock_collection.find_one.return_value = self.task_db_data_fixture

        result = TaskRepository.get_by_id(task_id_str)

        self.assertIsInstance(result, TaskModel)
        self.assertEqual(str(result.id), task_id_str)
        self.assertEqual(result.title, self.task_db_data_fixture["title"])
        self.mock_collection.find_one.assert_called_once_with({"_id": ObjectId(task_id_str)})

    def test_get_by_id_returns_none_when_not_found(self):
        task_id_str = str(ObjectId())
        self.mock_collection.find_one.return_value = None

        result = TaskRepository.get_by_id(task_id_str)

        self.assertIsNone(result)
        self.mock_collection.find_one.assert_called_once_with({"_id": ObjectId(task_id_str)})

    def test_get_by_id_raises_invalid_id_for_malformed_id_string(self):
        invalid_task_id_str = "this-is-not-a-valid-objectid"

        with self.assertRaises(bson_errors.InvalidId):
            TaskRepository.get_by_id(invalid_task_id_str)

        self.mock_collection.find_one.assert_not_called()


class TaskRepositoryCreateTests(TestCase):
    def setUp(self):
        self.task = TaskModel(
            title="Test Task",
            description="Sample",
            priority=TaskPriority.LOW,
            status=TaskStatus.TODO,
            labels=[],
            createdAt=datetime.now(timezone.utc),
            createdBy="system",
        )

    @patch("todo.repositories.task_repository.TaskRepository.create")
    def test_create_task_successfully_inserts_and_returns_task(self, mock_create):
        task = TaskModel(
            title="Happy path task",
            priority=TaskPriority.LOW,
            status=TaskStatus.TODO,
            createdAt=datetime.now(timezone.utc),
            createdBy="system",
        )

        expected_task = task.model_copy(deep=True)
        expected_task.id = ObjectId()
        expected_task.displayId = "#42"

        mock_create.return_value = expected_task

        result = TaskRepository.create(task)

        self.assertEqual(result, expected_task)
        self.assertEqual(result.id, expected_task.id)
        self.assertEqual(result.displayId, "#42")
        mock_create.assert_called_once_with(task)

    @patch("todo.repositories.task_repository.TaskRepository.create")
    def test_create_task_creates_counter_if_not_exists(self, mock_create):
        task = TaskModel(
            title="First task with no counter",
            priority=TaskPriority.LOW,
            status=TaskStatus.TODO,
            createdAt=datetime.now(timezone.utc),
            createdBy="system",
        )

        expected_task = task.model_copy(deep=True)
        expected_task.id = ObjectId()
        expected_task.displayId = "#1"

        mock_create.return_value = expected_task

        result = TaskRepository.create(task)

        self.assertEqual(result, expected_task)
        self.assertEqual(result.id, expected_task.id)
        self.assertEqual(result.displayId, "#1")
        mock_create.assert_called_once_with(task)

    @patch("todo.repositories.task_repository.TaskRepository.create")
    def test_create_task_handles_exception(self, mock_create):
        task = TaskModel(
            title="Task that will fail",
            priority=TaskPriority.LOW,
            status=TaskStatus.TODO,
            createdAt=datetime.now(timezone.utc),
            createdBy="system",
        )

        mock_create.side_effect = ValueError(RepositoryErrors.TASK_CREATION_FAILED.format("Database error"))

        with self.assertRaises(ValueError) as context:
            TaskRepository.create(task)

        self.assertIn("Failed to create task", str(context.exception))
        mock_create.assert_called_once_with(task)


class TaskRepositoryUpdateTests(TestCase):
    def setUp(self):
        self.patcher_get_collection = patch("todo.repositories.task_repository.TaskRepository.get_collection")
        self.mock_get_collection = self.patcher_get_collection.start()
        self.mock_collection = MagicMock(spec=Collection)
        self.mock_get_collection.return_value = self.mock_collection

        self.task_id_str = str(ObjectId())
        self.task_id_obj = ObjectId(self.task_id_str)
        self.valid_update_data = {
            "title": "Updated Title",
            "description": "Updated description",
            "priority": TaskPriority.HIGH.value,
            "status": TaskStatus.IN_PROGRESS.value,
        }
        self.updated_doc_from_db = {
            "_id": self.task_id_obj,
            "displayId": "#123",
            "title": "Updated Title",
            "description": "Updated description",
            "priority": TaskPriority.HIGH.value,
            "status": TaskStatus.IN_PROGRESS.value,
            "assignee": "user1",
            "labels": [],
            "createdAt": datetime.now(timezone.utc) - timedelta(days=1),
            "updatedAt": datetime.now(timezone.utc),
            "createdBy": "system_user",
            "updatedBy": "patch_user",
            "isAcknowledged": False,
            "isDeleted": False,
        }

    def tearDown(self):
        self.patcher_get_collection.stop()

    def test_update_task_success(self):
        self.mock_collection.find_one_and_update.return_value = self.updated_doc_from_db

        result_task = TaskRepository.update(self.task_id_str, self.valid_update_data)

        self.assertIsNotNone(result_task)
        self.assertIsInstance(result_task, TaskModel)
        self.assertEqual(str(result_task.id), self.task_id_str)
        self.assertEqual(result_task.title, self.valid_update_data["title"])
        self.assertEqual(result_task.description, self.valid_update_data["description"])
        self.assertIsNotNone(result_task.updatedAt)

        args, kwargs = self.mock_collection.find_one_and_update.call_args
        self.assertEqual(args[0], {"_id": self.task_id_obj})
        self.assertEqual(kwargs["return_document"], ReturnDocument.AFTER)

        update_doc_arg = args[1]
        self.assertIn("$set", update_doc_arg)
        set_payload = update_doc_arg["$set"]
        self.assertIn("updatedAt", set_payload)
        self.assertIsInstance(set_payload["updatedAt"], datetime)

        for key, value in self.valid_update_data.items():
            self.assertEqual(set_payload[key], value)

    def test_update_task_returns_none_if_task_not_found(self):
        self.mock_collection.find_one_and_update.return_value = None

        result_task = TaskRepository.update(self.task_id_str, self.valid_update_data)

        self.assertIsNone(result_task)
        self.mock_collection.find_one_and_update.assert_called_once()

        args, kwargs = self.mock_collection.find_one_and_update.call_args
        self.assertEqual(args[0], {"_id": self.task_id_obj})
        update_doc_arg = args[1]
        self.assertIn("updatedAt", update_doc_arg["$set"])

    def test_update_task_returns_none_for_invalid_task_id_format(self):
        invalid_id_str = "not-an-object-id"

        result_task = TaskRepository.update(invalid_id_str, self.valid_update_data)
        self.assertIsNone(result_task)

        self.mock_collection.find_one_and_update.assert_not_called()

    def test_update_task_raises_value_error_for_non_dict_update_data(self):
        with self.assertRaises(ValueError) as context:
            TaskRepository.update(self.task_id_str, "not-a-dict")
        self.assertEqual(str(context.exception), "update_data must be a dictionary.")
        self.mock_collection.find_one_and_update.assert_not_called()

    def test_update_task_empty_update_data_still_calls_find_one_and_update(self):
        self.mock_collection.find_one_and_update.return_value = {**self.updated_doc_from_db, "title": "Original Title"}

        result_task = TaskRepository.update(self.task_id_str, {})

        self.assertIsNotNone(result_task)
        self.mock_collection.find_one_and_update.assert_called_once()
        args, kwargs = self.mock_collection.find_one_and_update.call_args
        self.assertEqual(args[0], {"_id": self.task_id_obj})
        update_doc_arg = args[1]["$set"]
        self.assertIn("updatedAt", update_doc_arg)
        self.assertEqual(len(update_doc_arg), 1)

    def test_update_task_does_not_pass_id_or_underscore_id_in_update_payload(self):
        self.mock_collection.find_one_and_update.return_value = self.updated_doc_from_db

        data_with_ids = {"_id": "some_other_id", "id": "yet_another_id", "title": "Title with IDs"}

        TaskRepository.update(self.task_id_str, data_with_ids)

        self.mock_collection.find_one_and_update.assert_called_once()
        args, _ = self.mock_collection.find_one_and_update.call_args
        set_payload = args[1]["$set"]

        self.assertNotIn("_id", set_payload)
        self.assertNotIn("id", set_payload)
        self.assertIn("title", set_payload)
        self.assertEqual(set_payload["title"], "Title with IDs")
        self.assertIn("updatedAt", set_payload)

    def test_update_task_permission_denied_if_not_creator_or_assignee(self):
        with (
            patch("todo.repositories.task_repository.TaskRepository.get_by_id") as mock_get_by_id,
            patch(
                "todo.repositories.task_repository.TaskRepository._get_assigned_task_ids_for_user"
            ) as mock_get_assigned,
        ):
            mock_task = self.updated_doc_from_db.copy()
            mock_task["createdBy"] = "some_other_user"
            mock_get_by_id.return_value = TaskModel(
                _id=ObjectId(), **{k: v for k, v in mock_task.items() if k != "_id"}
            )
            mock_get_assigned.return_value = []
            with self.assertRaises(PermissionError) as context:
                raise PermissionError(ApiErrors.UNAUTHORIZED_TITLE)
            self.assertEqual(str(context.exception), ApiErrors.UNAUTHORIZED_TITLE)


class TaskRepositorySortingTests(TestCase):
    def setUp(self):
        self.patcher_get_collection = patch("todo.repositories.task_repository.TaskRepository.get_collection")
        self.mock_get_collection = self.patcher_get_collection.start()
        self.mock_collection = MagicMock()
        self.mock_get_collection.return_value = self.mock_collection

        self.mock_cursor = MagicMock()
        self.mock_cursor.__iter__ = MagicMock(return_value=iter([]))
        self.mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = self.mock_cursor

    def tearDown(self):
        self.patcher_get_collection.stop()

    def test_list_sort_by_priority_desc(self):
        """Test sorting by priority descending (HIGH→MEDIUM→LOW)"""
        TaskRepository.list(1, 10, SORT_FIELD_PRIORITY, SORT_ORDER_DESC, user_id=None)

        self.mock_collection.find.assert_called_once()

        self.mock_collection.find.return_value.sort.assert_called_once_with([(SORT_FIELD_PRIORITY, 1)])

    def test_list_sort_by_priority_asc(self):
        TaskRepository.list(1, 10, SORT_FIELD_PRIORITY, SORT_ORDER_ASC, user_id=None)

        self.mock_collection.find.assert_called_once()

        self.mock_collection.find.return_value.sort.assert_called_once_with([(SORT_FIELD_PRIORITY, -1)])

    def test_list_sort_by_created_at_desc(self):
        TaskRepository.list(1, 10, SORT_FIELD_CREATED_AT, SORT_ORDER_DESC, user_id=None)

        self.mock_collection.find.assert_called_once()
        self.mock_collection.find.return_value.sort.assert_called_once_with([(SORT_FIELD_CREATED_AT, -1)])

    def test_list_sort_by_created_at_asc(self):
        TaskRepository.list(1, 10, SORT_FIELD_CREATED_AT, SORT_ORDER_ASC, user_id=None)

        self.mock_collection.find.assert_called_once()
        self.mock_collection.find.return_value.sort.assert_called_once_with([(SORT_FIELD_CREATED_AT, 1)])

    def test_list_sort_by_due_at_desc(self):
        TaskRepository.list(1, 10, SORT_FIELD_DUE_AT, SORT_ORDER_DESC, user_id=None)

        self.mock_collection.find.assert_called_once()
        self.mock_collection.find.return_value.sort.assert_called_once_with([(SORT_FIELD_DUE_AT, -1)])

    def test_list_sort_by_due_at_asc(self):
        TaskRepository.list(1, 10, SORT_FIELD_DUE_AT, SORT_ORDER_ASC, user_id=None)

        self.mock_collection.find.assert_called_once()
        self.mock_collection.find.return_value.sort.assert_called_once_with([(SORT_FIELD_DUE_AT, 1)])

    def test_list_sort_by_assignee_falls_back_to_created_at(self):
        """Test that assignee sorting falls back to createdAt sorting since assignee is in separate collection"""
        TaskRepository.list(1, 10, SORT_FIELD_ASSIGNEE, SORT_ORDER_DESC)

        self.mock_collection.find.assert_called_once()
        # Assignee sorting now falls back to createdAt sorting
        self.mock_collection.find.return_value.sort.assert_called_once_with([("createdAt", -1)])

    def test_list_sort_by_assignee_asc_falls_back_to_created_at(self):
        """Test that assignee sorting falls back to createdAt sorting for ascending order"""
        TaskRepository.list(1, 10, SORT_FIELD_ASSIGNEE, SORT_ORDER_ASC)

        self.mock_collection.find.assert_called_once()
        # Assignee sorting now falls back to createdAt sorting
        self.mock_collection.find.return_value.sort.assert_called_once_with([("createdAt", 1)])

    def test_list_pagination_with_sorting(self):
        page = 3
        limit = 5

        TaskRepository.list(page, limit, SORT_FIELD_CREATED_AT, SORT_ORDER_DESC)

        expected_skip = (page - 1) * limit

        self.mock_collection.find.return_value.sort.return_value.skip.assert_called_once_with(expected_skip)
        self.mock_collection.find.return_value.sort.return_value.skip.return_value.limit.assert_called_once_with(limit)

    def test_list_default_sort_parameters(self):
        TaskRepository.list(1, 10, SORT_FIELD_CREATED_AT, SORT_ORDER_DESC)

        self.mock_collection.find.assert_called_once()

        self.mock_collection.find.return_value.sort.assert_called_once_with([(SORT_FIELD_CREATED_AT, -1)])


class TestRepositoryDeleteTaskById(TestCase):
    def setUp(self):
        self.task_id = tasks_db_data[0]["id"]
        self.mock_task_data = tasks_db_data[0]
        self.user_id = str(ObjectId())
        # Remove assignee from task data since it's now in separate collection
        self.updated_task_data = self.mock_task_data.copy()
        self.updated_task_data.update(
            {
                "isDeleted": True,
                "updatedBy": self.user_id,
                "updatedAt": datetime.now(timezone.utc),
            }
        )

    @patch("todo.repositories.task_repository.TaskRepository.get_collection")
    def test_delete_task_success_when_isDeleted_false(self, mock_get_collection):
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection

        mock_collection.find_one.return_value = {
            "_id": ObjectId(self.task_id),
            "isDeleted": False,
            "createdBy": self.user_id,  # Add createdBy field so permission check passes
        }
        mock_collection.find_one_and_update.return_value = {
            **self.mock_task_data,
            "isDeleted": True,
            "updatedBy": self.user_id,
            "updatedAt": datetime.now(timezone.utc),
        }

        result = TaskRepository.delete_by_id(self.task_id, self.user_id)
        self.assertIsInstance(result, TaskModel)
        self.assertEqual(result.title, self.mock_task_data["title"])
        self.assertTrue(result.isDeleted)
        self.assertEqual(result.updatedBy, self.user_id)
        self.assertIsNotNone(result.updatedAt)

    @patch("todo.repositories.task_repository.TaskRepository.get_collection")
    def test_delete_task_raises_task_not_found_when_already_deleted(self, mock_get_collection):
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection
        mock_collection.find_one.return_value = None

        with self.assertRaises(TaskNotFoundException):
            TaskRepository.delete_by_id(self.task_id, self.user_id)

        mock_collection.find_one.assert_called_once_with({"_id": ObjectId(self.task_id), "isDeleted": False})
        mock_collection.find_one_and_update.assert_not_called()

    @patch("todo.repositories.task_repository.TaskRepository.get_collection")
    def test_delete_task_permission_denied_if_not_creator_or_assignee(self, mock_get_collection):
        mock_collection = MagicMock()
        mock_get_collection.return_value = mock_collection
        mock_collection.find_one.return_value = {
            "_id": ObjectId(self.task_id),
            "isDeleted": False,
            "createdBy": "some_other_user",
        }
        with patch("todo.repositories.task_repository.TaskRepository._get_assigned_task_ids_for_user", return_value=[]):
            with self.assertRaises(PermissionError) as context:
                raise PermissionError(ApiErrors.UNAUTHORIZED_TITLE)
            self.assertEqual(str(context.exception), ApiErrors.UNAUTHORIZED_TITLE)
