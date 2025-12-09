from rest_framework.reverse import reverse
from rest_framework import status
from unittest.mock import patch, Mock
from rest_framework.response import Response
from django.conf import settings
from datetime import datetime, timedelta, timezone
from bson.objectid import ObjectId
from bson.errors import InvalidId as BsonInvalidId
from todo.tests.integration.base_mongo_test import AuthenticatedMongoTestCase
from todo.dto.user_dto import UserDTO
from todo.dto.task_dto import TaskDTO
from todo.dto.responses.get_tasks_response import GetTasksResponse
from todo.dto.responses.create_task_response import CreateTaskResponse
from todo.tests.fixtures.task import task_dtos
from todo.constants.task import (
    TaskPriority,
    TaskStatus,
    SORT_FIELD_PRIORITY,
    SORT_FIELD_DUE_AT,
    SORT_FIELD_CREATED_AT,
    SORT_FIELD_UPDATED_AT,
    SORT_FIELD_ASSIGNEE,
    SORT_ORDER_ASC,
    SORT_ORDER_DESC,
)
from todo.dto.responses.get_task_by_id_response import GetTaskByIdResponse
from todo.exceptions.task_exceptions import TaskNotFoundException, UnprocessableEntityException
from todo.constants.messages import ValidationErrors, ApiErrors
from todo.dto.responses.error_response import ApiErrorResponse, ApiErrorDetail
from rest_framework.exceptions import ValidationError as DRFValidationError
from todo.dto.deferred_details_dto import DeferredDetailsDTO
from rest_framework.test import APIClient
from todo.dto.task_assignment_dto import TaskAssignmentDTO


class TaskViewTests(AuthenticatedMongoTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("tasks")
        self.valid_params = {"page": 1, "limit": 10}

    @patch("todo.services.task_service.TaskService.get_tasks")
    def test_get_tasks_returns_200_for_valid_params(self, mock_get_tasks: Mock):
        mock_get_tasks.return_value = GetTasksResponse(tasks=task_dtos)

        response: Response = self.client.get(self.url, self.valid_params)

        mock_get_tasks.assert_called_once_with(
            page=1,
            limit=10,
            sort_by="updatedAt",
            order="desc",
            user_id=str(self.user_id),
            team_id=None,
            status_filter=None,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_response = mock_get_tasks.return_value.model_dump(mode="json")
        self.assertDictEqual(response.data, expected_response)

    @patch("todo.services.task_service.TaskService.get_tasks")
    def test_get_tasks_returns_200_without_params(self, mock_get_tasks: Mock):
        mock_get_tasks.return_value = GetTasksResponse(tasks=task_dtos)

        response: Response = self.client.get(self.url)
        default_limit = settings.REST_FRAMEWORK["DEFAULT_PAGINATION_SETTINGS"]["DEFAULT_PAGE_LIMIT"]
        mock_get_tasks.assert_called_once_with(
            page=1,
            limit=default_limit,
            sort_by="updatedAt",
            order="desc",
            user_id=str(self.user_id),
            team_id=None,
            status_filter=None,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_tasks_returns_400_for_invalid_query_params(self):
        invalid_params = {
            "page": "invalid",
            "limit": -1,
        }

        response: Response = self.client.get(self.url, invalid_params)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        expected_response = {
            "statusCode": 400,
            "message": "A valid integer is required.",
            "errors": [
                {"source": {"parameter": "page"}, "detail": "A valid integer is required."},
                {"source": {"parameter": "limit"}, "detail": "limit must be greater than or equal to 1"},
            ],
        }
        response_data = response.data

        self.assertEqual(response_data["statusCode"], expected_response["statusCode"])
        self.assertEqual(response_data["message"], expected_response["message"], "Error message mismatch")

        for actual_error, expected_error in zip(response_data["errors"], expected_response["errors"]):
            self.assertEqual(actual_error["source"]["parameter"], expected_error["source"]["parameter"])
            self.assertEqual(actual_error["detail"], expected_error["detail"])

    @patch("todo.services.task_service.TaskService.get_task_by_id")
    def test_get_single_task_success(self, mock_get_task_by_id: Mock):
        valid_task_id = str(ObjectId())
        mock_task_data = task_dtos[0]
        mock_get_task_by_id.return_value = mock_task_data

        expected_response_obj = GetTaskByIdResponse(data=mock_task_data)

        response = self.client.get(reverse("task_detail", args=[valid_task_id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, expected_response_obj.model_dump(mode="json"))
        mock_get_task_by_id.assert_called_once_with(valid_task_id)

    @patch("todo.services.task_service.TaskService.get_task_by_id")
    def test_get_single_task_not_found(self, mock_get_task_by_id: Mock):
        non_existent_task_id = str(ObjectId())
        expected_error_message = ApiErrors.TASK_NOT_FOUND.format(non_existent_task_id)
        mock_get_task_by_id.side_effect = TaskNotFoundException(task_id=non_existent_task_id)

        response = self.client.get(reverse("task_detail", args=[non_existent_task_id]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["statusCode"], status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["message"], expected_error_message)
        self.assertEqual(len(response.data["errors"]), 1)
        self.assertEqual(response.data["errors"][0]["source"], {"path": "task_id"})
        self.assertEqual(response.data["errors"][0]["title"], ApiErrors.RESOURCE_NOT_FOUND_TITLE)
        self.assertEqual(response.data["errors"][0]["detail"], expected_error_message)
        mock_get_task_by_id.assert_called_once_with(non_existent_task_id)

    @patch("todo.services.task_service.TaskService.get_task_by_id")
    def test_get_single_task_invalid_id_format(self, mock_get_task_by_id: Mock):
        invalid_task_id = "invalid-id-string"
        mock_get_task_by_id.side_effect = ValueError(ValidationErrors.INVALID_TASK_ID_FORMAT)

        response = self.client.get(reverse("task_detail", args=[invalid_task_id]))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["statusCode"], status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["message"], ValidationErrors.INVALID_TASK_ID_FORMAT)
        self.assertEqual(len(response.data["errors"]), 1)
        self.assertEqual(response.data["errors"][0]["source"], {"path": "task_id"})
        self.assertEqual(response.data["errors"][0]["title"], ApiErrors.VALIDATION_ERROR)
        self.assertEqual(response.data["errors"][0]["detail"], ValidationErrors.INVALID_TASK_ID_FORMAT)
        mock_get_task_by_id.assert_called_once_with(invalid_task_id)

    @patch("todo.services.task_service.TaskService.get_task_by_id")
    def test_get_single_task_unexpected_error(self, mock_get_task_by_id: Mock):
        task_id = str(ObjectId())
        mock_get_task_by_id.side_effect = Exception("Some random error")

        response = self.client.get(reverse("task_detail", args=[task_id]))

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["statusCode"], status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["message"], ApiErrors.INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["errors"][0]["detail"], ApiErrors.INTERNAL_SERVER_ERROR)
        mock_get_task_by_id.assert_called_once_with(task_id)


class TaskViewTest(AuthenticatedMongoTestCase):
    def setUp(self):
        super().setUp()

    @patch("todo.services.task_service.TaskService.get_tasks")
    def test_get_tasks_with_default_pagination(self, mock_get_tasks):
        """Test GET /tasks without any query parameters uses default pagination"""
        mock_get_tasks.return_value = GetTasksResponse(tasks=task_dtos)

        response = self.client.get("/v1/tasks")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        default_limit = settings.REST_FRAMEWORK["DEFAULT_PAGINATION_SETTINGS"]["DEFAULT_PAGE_LIMIT"]
        mock_get_tasks.assert_called_once_with(
            page=1,
            limit=default_limit,
            sort_by="updatedAt",
            order="desc",
            user_id=str(self.user_id),
            team_id=None,
            status_filter=None,
        )

    @patch("todo.services.task_service.TaskService.get_tasks")
    def test_get_tasks_with_valid_pagination(self, mock_get_tasks):
        """Test GET /tasks with valid page and limit parameters"""
        mock_get_tasks.return_value = GetTasksResponse(tasks=task_dtos)

        response = self.client.get("/v1/tasks", {"page": "2", "limit": "15"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_tasks.assert_called_once_with(
            page=2,
            limit=15,
            sort_by="updatedAt",
            order="desc",
            user_id=str(self.user_id),
            team_id=None,
            status_filter=None,
        )

    def test_get_tasks_with_invalid_page(self):
        """Test GET /tasks with invalid page parameter"""
        response = self.client.get("/v1/tasks", {"page": "0"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_detail = str(response.data)
        self.assertIn("page", error_detail)
        self.assertIn("greater than or equal to 1", error_detail)

    def test_get_tasks_with_invalid_limit(self):
        """Test GET /tasks with invalid limit parameter"""
        response = self.client.get("/v1/tasks", {"limit": "0"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_detail = str(response.data)
        self.assertIn("limit", error_detail)
        self.assertIn("greater than or equal to 1", error_detail)

    def test_get_tasks_with_non_numeric_parameters(self):
        """Test GET /tasks with non-numeric parameters"""
        response = self.client.get("/v1/tasks", {"page": "abc", "limit": "def"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_detail = str(response.data)
        self.assertTrue("page" in error_detail or "limit" in error_detail)


class TaskViewSortingTests(AuthenticatedMongoTestCase):
    def setUp(self):
        super().setUp()

    @patch("todo.services.task_service.TaskService.get_tasks")
    def test_get_tasks_with_sort_by_priority(self, mock_get_tasks):
        mock_get_tasks.return_value = GetTasksResponse(tasks=task_dtos)

        response = self.client.get("/v1/tasks", {"sort_by": "priority"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_tasks.assert_called_once_with(
            page=1,
            limit=20,
            sort_by=SORT_FIELD_PRIORITY,
            order="desc",
            user_id=str(self.user_id),
            team_id=None,
            status_filter=None,
        )

    @patch("todo.services.task_service.TaskService.get_tasks")
    def test_get_tasks_with_sort_by_and_order(self, mock_get_tasks):
        mock_get_tasks.return_value = GetTasksResponse(tasks=task_dtos)

        response = self.client.get("/v1/tasks", {"sort_by": "dueAt", "order": "desc"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_tasks.assert_called_once_with(
            page=1,
            limit=20,
            sort_by=SORT_FIELD_DUE_AT,
            order=SORT_ORDER_DESC,
            user_id=str(self.user_id),
            team_id=None,
            status_filter=None,
        )

    @patch("todo.services.task_service.TaskService.get_tasks")
    def test_get_tasks_with_all_sort_fields(self, mock_get_tasks):
        mock_get_tasks.return_value = GetTasksResponse(tasks=task_dtos)

        sort_fields_with_expected_orders = [
            (SORT_FIELD_PRIORITY, "desc"),
            (SORT_FIELD_DUE_AT, "asc"),
            (SORT_FIELD_CREATED_AT, "desc"),
            (SORT_FIELD_UPDATED_AT, "desc"),
            (SORT_FIELD_ASSIGNEE, "asc"),
        ]

        for sort_field, expected_order in sort_fields_with_expected_orders:
            with self.subTest(sort_field=sort_field):
                mock_get_tasks.reset_mock()

                response = self.client.get("/v1/tasks", {"sort_by": sort_field})

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                mock_get_tasks.assert_called_once_with(
                    page=1,
                    limit=20,
                    sort_by=sort_field,
                    order=expected_order,
                    user_id=str(self.user_id),
                    team_id=None,
                    status_filter=None,
                )

    @patch("todo.services.task_service.TaskService.get_tasks")
    def test_get_tasks_with_all_order_values(self, mock_get_tasks):
        mock_get_tasks.return_value = GetTasksResponse(tasks=task_dtos)

        order_values = [SORT_ORDER_ASC, SORT_ORDER_DESC]

        for order in order_values:
            with self.subTest(order=order):
                mock_get_tasks.reset_mock()

                response = self.client.get("/v1/tasks", {"sort_by": SORT_FIELD_PRIORITY, "order": order})

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                mock_get_tasks.assert_called_once_with(
                    page=1,
                    limit=20,
                    sort_by=SORT_FIELD_PRIORITY,
                    order=order,
                    user_id=str(self.user_id),
                    team_id=None,
                    status_filter=None,
                )

    def test_get_tasks_with_invalid_sort_by(self):
        response = self.client.get("/v1/tasks", {"sort_by": "invalid_field"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        error_detail = str(response.data)
        self.assertIn("sort_by", error_detail)

    def test_get_tasks_with_invalid_order(self):
        response = self.client.get("/v1/tasks", {"sort_by": SORT_FIELD_PRIORITY, "order": "invalid_order"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        error_detail = str(response.data)
        self.assertIn("order", error_detail)

    @patch("todo.services.task_service.TaskService.get_tasks")
    def test_get_tasks_sorting_with_pagination(self, mock_get_tasks):
        mock_get_tasks.return_value = GetTasksResponse(tasks=task_dtos)

        response = self.client.get(
            "/v1/tasks", {"page": "2", "limit": "15", "sort_by": SORT_FIELD_DUE_AT, "order": SORT_ORDER_ASC}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_tasks.assert_called_once_with(
            page=2,
            limit=15,
            sort_by=SORT_FIELD_DUE_AT,
            order=SORT_ORDER_ASC,
            user_id=str(self.user_id),
            team_id=None,
            status_filter=None,
        )

    @patch("todo.services.task_service.TaskService.get_tasks")
    def test_get_tasks_default_behavior_unchanged(self, mock_get_tasks):
        mock_get_tasks.return_value = GetTasksResponse(tasks=task_dtos)

        response = self.client.get("/v1/tasks")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_tasks.assert_called_once_with(
            page=1,
            limit=20,
            sort_by=SORT_FIELD_UPDATED_AT,
            order="desc",
            user_id=str(self.user_id),
            team_id=None,
            status_filter=None,
        )

    def test_get_tasks_edge_case_combinations(self):
        with patch("todo.services.task_service.TaskService.get_tasks") as mock_get_tasks:
            mock_get_tasks.return_value = GetTasksResponse(tasks=task_dtos)

            response = self.client.get("/v1/tasks", {"order": SORT_ORDER_ASC})

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_get_tasks.assert_called_once_with(
                page=1,
                limit=20,
                sort_by=SORT_FIELD_UPDATED_AT,
                order=SORT_ORDER_ASC,
                user_id=str(self.user_id),
                team_id=None,
                status_filter=None,
            )


class CreateTaskViewTests(AuthenticatedMongoTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("tasks")
        self.user_id = str(ObjectId())

        self.valid_payload = {
            "title": "Write tests",
            "description": "Cover all core paths",
            "priority": "HIGH",
            "status": "IN_PROGRESS",
            "assignee": {"assignee_id": self.user_id, "user_type": "user"},
            "labels": [],
            "dueAt": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
            "timezone": "Asia/Calcutta",
        }

    @patch("todo.services.task_service.TaskService.create_task")
    def test_create_task_returns_201_on_success(self, mock_create_task):
        task_dto = TaskDTO(
            id="abc123",
            displayId="#1",
            title=self.valid_payload["title"],
            description=self.valid_payload["description"],
            priority=TaskPriority[self.valid_payload["priority"]],
            status=TaskStatus[self.valid_payload["status"]],
            assignee=TaskAssignmentDTO(
                id="assignment-1",
                task_id="task-1",
                assignee_id="user-1",
                user_type="user",
                is_active=True,
                created_by="user-1",
                created_at=datetime.now(timezone.utc),
                assignee_name="SYSTEM",
            ),
            isAcknowledged=False,
            labels=[],
            startedAt=datetime.now(timezone.utc),
            dueAt=datetime.fromisoformat(self.valid_payload["dueAt"].replace("Z", "+00:00")),
            createdAt=datetime.now(timezone.utc),
            updatedAt=None,
            createdBy=UserDTO(id="system", name="SYSTEM"),
            updatedBy=None,
        )

        mock_create_task.return_value = CreateTaskResponse(data=task_dto)

        response: Response = self.client.post(self.url, data=self.valid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("data", response.data)
        self.assertEqual(response.data["data"]["title"], self.valid_payload["title"])
        mock_create_task.assert_called_once()

    def test_create_task_returns_400_when_title_is_missing(self):
        invalid_payload = self.valid_payload.copy()
        del invalid_payload["title"]

        response = self.client.post(self.url, data=invalid_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["statusCode"], 400)
        self.assertEqual(response.data["message"], "Validation Error")
        self.assertTrue(any(error["source"]["parameter"] == "title" for error in response.data["errors"]))

    def test_create_task_returns_400_when_title_blank(self):
        invalid_payload = self.valid_payload.copy()
        invalid_payload["title"] = " "

        response = self.client.post(self.url, data=invalid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(any(error["source"]["parameter"] == "title" for error in response.data["errors"]))

    def test_create_task_returns_400_for_invalid_priority(self):
        invalid_payload = self.valid_payload.copy()
        invalid_payload["priority"] = "SUPER"

        response = self.client.post(self.url, data=invalid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(any(error["source"]["parameter"] == "priority" for error in response.data["errors"]))

    def test_create_task_returns_400_for_invalid_status(self):
        invalid_payload = self.valid_payload.copy()
        invalid_payload["status"] = "WORKING"

        response = self.client.post(self.url, data=invalid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(any(error["source"]["parameter"] == "status" for error in response.data["errors"]))

    def test_create_task_returns_400_when_label_ids_are_not_objectids(self):
        invalid_payload = self.valid_payload.copy()
        invalid_payload["labels"] = ["invalid_id"]

        response = self.client.post(self.url, data=invalid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(any(error["source"]["parameter"] == "labels" for error in response.data["errors"]))

    def test_create_task_returns_400_when_dueAt_is_past(self):
        invalid_payload = self.valid_payload.copy()
        invalid_payload["dueAt"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        invalid_payload["timezone"] = "Asia/Kolkata"

        response = self.client.post(self.url, data=invalid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(any(error["source"]["parameter"] == "dueAt" for error in response.data["errors"]))

    @patch("todo.services.task_service.TaskService.create_task")
    def test_create_task_returns_500_on_internal_error(self, mock_create_task):
        mock_create_task.side_effect = Exception("Database exploded")

        try:
            response = self.client.post(self.url, data=self.valid_payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
            self.assertEqual(response.data["message"], ApiErrors.INTERNAL_SERVER_ERROR)
        except Exception as e:
            self.assertEqual(str(e), "Database exploded")


class TaskDeleteViewTests(AuthenticatedMongoTestCase):
    def setUp(self):
        super().setUp()
        self.valid_task_id = str(ObjectId())
        self.url = reverse("task_detail", kwargs={"task_id": self.valid_task_id})

    @patch("todo.services.task_service.TaskService.delete_task")
    def test_delete_task_returns_204_on_success(self, mock_delete_task: Mock):
        mock_delete_task.return_value = None
        response = self.client.delete(self.url)
        mock_delete_task.assert_called_once_with(ObjectId(self.valid_task_id), str(self.user_id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.data, None)

    @patch("todo.services.task_service.TaskService.delete_task")
    def test_delete_task_returns_404_when_not_found(self, mock_delete_task: Mock):
        mock_delete_task.side_effect = TaskNotFoundException(self.valid_task_id)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn(ApiErrors.TASK_NOT_FOUND.format(self.valid_task_id), response.data["message"])

    @patch("todo.services.task_service.TaskService.delete_task")
    def test_delete_task_returns_400_for_invalid_id_format(self, mock_delete_task: Mock):
        mock_delete_task.side_effect = BsonInvalidId()
        invalid_url = reverse("task_detail", kwargs={"task_id": "invalid-id"})
        response = self.client.delete(invalid_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(ValidationErrors.INVALID_TASK_ID_FORMAT, response.data["message"])


class TaskUpdateViewTests(AuthenticatedMongoTestCase):
    def setUp(self):
        super().setUp()
        self.task_id_str = str(ObjectId())
        self.task_url = f"/v1/tasks/{self.task_id_str}/update"

        # Create a mock task DTO for testing
        self.updated_task_dto_fixture = TaskDTO(
            id=self.task_id_str,
            displayId="#TSK1",
            title="Updated Task Title",
            description="Updated Description",
            priority=TaskPriority.HIGH,
            status=TaskStatus.IN_PROGRESS,
            labels=[],
            dueAt=datetime.now(timezone.utc) + timedelta(days=5),
            startedAt=datetime.now(timezone.utc),
            isAcknowledged=True,
            createdAt=datetime.now(timezone.utc),
            updatedAt=datetime.now(timezone.utc),
            createdBy=UserDTO(id=str(self.user_id), name="Test User"),
            updatedBy=UserDTO(id=str(self.user_id), name="Test User"),
            assignee=TaskAssignmentDTO(
                id=str(ObjectId()),
                task_id=self.task_id_str,
                assignee_id=str(ObjectId()),
                user_type="user",
                is_active=True,
                created_by=str(self.user_id),
                updated_by=None,
                created_at=datetime.now(timezone.utc),
                updated_at=None,
            ),
            deferredDetails=None,
            in_watchlist=None,
        )

    @patch("todo.views.task.UpdateTaskSerializer")
    @patch("todo.views.task.TaskService.update_task_with_assignee_from_dict")
    def test_patch_task_and_assignee_success(self, mock_service_update_task, mock_update_serializer_class):
        future_date = datetime.now(timezone.utc) + timedelta(days=5)
        assignee_id = str(ObjectId())

        valid_payload = {
            "title": "Updated Task Title",
            "description": "Updated Description",
            "priority": TaskPriority.HIGH.name,
            "status": TaskStatus.IN_PROGRESS.name,
            "assignee": {"assignee_id": assignee_id, "user_type": "user"},
            "dueAt": future_date.isoformat(),
        }

        mock_serializer_instance = Mock()
        mock_serializer_instance.is_valid.return_value = True
        mock_serializer_instance.validated_data = {
            "title": "Updated Task Title",
            "description": "Updated Description",
            "priority": TaskPriority.HIGH.name,
            "status": TaskStatus.IN_PROGRESS.name,
            "assignee": {"assignee_id": assignee_id, "user_type": "user"},
            "dueAt": future_date,
        }
        mock_update_serializer_class.return_value = mock_serializer_instance

        mock_service_update_task.return_value = self.updated_task_dto_fixture

        response = self.client.patch(self.task_url, data=valid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that the serializer was called with the correct data
        mock_update_serializer_class.assert_called_once()
        call_args = mock_update_serializer_class.call_args
        self.assertEqual(call_args[1]["partial"], True)

        mock_serializer_instance.is_valid.assert_called_once()
        mock_service_update_task.assert_called_once()

        expected_response_data = self.updated_task_dto_fixture.model_dump(mode="json")
        self.assertEqual(response.data, expected_response_data)

    @patch("todo.views.task.UpdateTaskSerializer")
    def test_patch_task_and_assignee_validation_error(self, mock_update_serializer_class):
        invalid_payload = {
            "title": "",  # Invalid: empty title
            "priority": "INVALID_PRIORITY",  # Invalid priority
        }

        mock_serializer_instance = Mock()
        mock_serializer_instance.is_valid.return_value = False
        mock_serializer_instance.errors = {
            "title": ["Title cannot be blank"],
            "priority": ["Invalid priority value"],
        }
        mock_update_serializer_class.return_value = mock_serializer_instance

        response = self.client.patch(self.task_url, data=invalid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("errors", response.data)
        self.assertEqual(response.data["statusCode"], 400)

    @patch("todo.views.task.UpdateTaskSerializer")
    @patch("todo.views.task.TaskService.update_task_with_assignee_from_dict")
    def test_patch_task_and_assignee_task_not_found(self, mock_service_update_task, mock_update_serializer_class):
        valid_payload = {"title": "Updated Title"}

        mock_serializer_instance = Mock()
        mock_serializer_instance.is_valid.return_value = True
        mock_serializer_instance.validated_data = {"title": "Updated Title"}
        mock_update_serializer_class.return_value = mock_serializer_instance

        mock_service_update_task.side_effect = TaskNotFoundException(self.task_id_str)

        response = self.client.patch(self.task_url, data=valid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("errors", response.data)

    @patch("todo.views.task.UpdateTaskSerializer")
    @patch("todo.views.task.TaskService.update_task_with_assignee_from_dict")
    def test_patch_task_and_assignee_permission_denied(self, mock_service_update_task, mock_update_serializer_class):
        valid_payload = {"title": "Updated Title"}

        mock_serializer_instance = Mock()
        mock_serializer_instance.is_valid.return_value = True
        mock_serializer_instance.validated_data = {"title": "Updated Title"}
        mock_update_serializer_class.return_value = mock_serializer_instance

        mock_service_update_task.side_effect = PermissionError(ApiErrors.UNAUTHORIZED_TITLE)

        response = self.client.patch(self.task_url, data=valid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("errors", response.data)

    def test_patch_task_and_assignee_unauthenticated(self):
        # Create a new client without authentication
        unauthenticated_client = APIClient()
        response = unauthenticated_client.patch(self.task_url, data={}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TaskDetailViewPatchTests(AuthenticatedMongoTestCase):
    def setUp(self):
        super().setUp()
        self.task_id_str = str(ObjectId())
        self.task_url = reverse("task_detail", args=[self.task_id_str])
        self.future_date = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

        self.updated_task_dto_fixture = TaskDTO(
            id=self.task_id_str,
            displayId="#UPD1",
            title="Updated Title from View Test",
            description="Updated description.",
            priority=TaskPriority.HIGH.value,
            status=TaskStatus.IN_PROGRESS.value,
            assignee=TaskAssignmentDTO(
                id="assignment-1",
                task_id="task-1",
                assignee_id="user-1",
                user_type="user",
                is_active=True,
                created_by="user-1",
                created_at=datetime.now(timezone.utc) - timedelta(days=2),
                assignee_name="SYSTEM",
            ),
            isAcknowledged=True,
            labels=[],
            startedAt=datetime.now(timezone.utc) - timedelta(hours=1),
            dueAt=datetime.fromisoformat(
                self.future_date.replace("Z", "+00:00") if "Z" in self.future_date else self.future_date
            ),
            in_watchlist=None,
            createdAt=datetime.now(timezone.utc) - timedelta(days=2),
            updatedAt=datetime.now(timezone.utc),
            createdBy=UserDTO(id="system_creator", name="SYSTEM"),
            updatedBy=UserDTO(id="system_patch_user", name="SYSTEM"),
        )

    @patch("todo.views.task.UpdateTaskSerializer")
    @patch("todo.views.task.TaskService.update_task")
    def test_patch_task_success(self, mock_service_update_task, mock_update_serializer_class):
        valid_payload = {
            "title": "Updated Title from View Test",
            "priority": TaskPriority.HIGH.name,
            "dueAt": self.future_date,
        }

        mock_serializer_instance = Mock()
        mock_serializer_instance.is_valid.return_value = True
        mock_serializer_instance.validated_data = valid_payload
        mock_update_serializer_class.return_value = mock_serializer_instance

        mock_service_update_task.return_value = self.updated_task_dto_fixture

        response = self.client.patch(self.task_url, data=valid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_update_serializer_class.assert_called_once_with(data=valid_payload, partial=True)
        mock_serializer_instance.is_valid.assert_called_once_with(raise_exception=True)
        mock_service_update_task.assert_called_once_with(
            task_id=self.task_id_str, validated_data=valid_payload, user_id=str(self.user_id)
        )

        expected_response_data = self.updated_task_dto_fixture.model_dump(mode="json")
        self.assertEqual(response.data, expected_response_data)

    @patch("todo.views.task.UpdateTaskSerializer")
    def test_patch_task_serializer_invalid_data(self, mock_update_serializer_class):
        invalid_payload = {"title": "   ", "dueAt": "not-a-date"}

        mock_serializer_instance = Mock()
        error_detail = {"title": [ValidationErrors.BLANK_TITLE], "dueAt": ["Invalid date format."]}
        mock_serializer_instance.is_valid.side_effect = DRFValidationError(detail=error_detail)
        mock_update_serializer_class.return_value = mock_serializer_instance

        response = self.client.patch(self.task_url, data=invalid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("errors", response.data)
        errors_list = response.data["errors"]

        title_error_found = any(
            err.get("source", {}).get("parameter") == "title" and ValidationErrors.BLANK_TITLE in err.get("detail", "")
            for err in errors_list
        )
        due_at_error_found = any(
            err.get("source", {}).get("parameter") == "dueAt" and "Invalid date format" in err.get("detail", "")
            for err in errors_list
        )

        self.assertTrue(title_error_found, "Title validation error not found in response as expected.")
        self.assertTrue(due_at_error_found, "dueAt validation error not found in response as expected.")

    @patch("todo.views.task.TaskService.update_task")
    @patch("todo.views.task.UpdateTaskSerializer")
    def test_patch_task_service_raises_task_not_found(self, mock_update_serializer_class, mock_service_update_task):
        valid_payload = {"title": "Attempt to update non-existent task"}

        mock_serializer_instance = Mock()
        mock_serializer_instance.is_valid.return_value = True
        mock_serializer_instance.validated_data = valid_payload
        mock_update_serializer_class.return_value = mock_serializer_instance

        mock_service_update_task.side_effect = TaskNotFoundException(task_id=self.task_id_str)

        response = self.client.patch(self.task_url, data=valid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        expected_message = ApiErrors.TASK_NOT_FOUND.format(self.task_id_str)
        self.assertEqual(response.data["statusCode"], status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["message"], expected_message)
        self.assertEqual(response.data["errors"][0]["detail"], expected_message)
        self.assertEqual(response.data["errors"][0]["title"], ApiErrors.RESOURCE_NOT_FOUND_TITLE)
        self.assertEqual(response.data["errors"][0]["source"]["path"], "task_id")

    @patch("todo.views.task.TaskService.update_task")
    @patch("todo.views.task.UpdateTaskSerializer")
    def test_patch_task_service_raises_bson_invalid_id_for_task_id(
        self, mock_update_serializer_class, mock_service_update_task
    ):
        invalid_task_id_format = "not-a-valid-object-id"
        url_with_invalid_id = reverse("task_detail", args=[invalid_task_id_format])
        valid_payload = {"title": "Update with invalid task ID format"}

        mock_serializer_instance = Mock()
        mock_serializer_instance.is_valid.return_value = True
        mock_serializer_instance.validated_data = valid_payload
        mock_update_serializer_class.return_value = mock_serializer_instance

        mock_service_update_task.side_effect = BsonInvalidId(ValidationErrors.INVALID_TASK_ID_FORMAT)

        response = self.client.patch(url_with_invalid_id, data=valid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["statusCode"], status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["message"], ValidationErrors.INVALID_TASK_ID_FORMAT)
        self.assertEqual(response.data["errors"][0]["detail"], ValidationErrors.INVALID_TASK_ID_FORMAT)
        self.assertEqual(response.data["errors"][0]["title"], ApiErrors.VALIDATION_ERROR)
        self.assertEqual(response.data["errors"][0]["source"]["path"], "task_id")

    @patch("todo.views.task.TaskService.update_task")
    @patch("todo.views.task.UpdateTaskSerializer")
    def test_patch_task_service_raises_drf_validation_error(
        self, mock_update_serializer_class, mock_service_update_task
    ):
        valid_payload = {"labels": ["some_valid_id", "a_label_id_that_service_finds_missing"]}

        mock_serializer_instance = Mock()
        mock_serializer_instance.is_valid.return_value = True
        mock_serializer_instance.validated_data = valid_payload
        mock_update_serializer_class.return_value = mock_serializer_instance

        service_error_detail = {
            "labels": [ValidationErrors.MISSING_LABEL_IDS.format("a_label_id_that_service_finds_missing")]
        }
        mock_service_update_task.side_effect = DRFValidationError(detail=service_error_detail)

        response = self.client.patch(self.task_url, data=valid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["statusCode"], status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["message"], service_error_detail["labels"][0])

        self.assertIn(
            "labels",
            response.data["errors"][0]["source"]["parameter"],
            "Source parameter should indicate 'labels' field",
        )
        self.assertEqual(response.data["errors"][0]["detail"], service_error_detail["labels"][0])

    @patch("todo.views.task.TaskService.update_task")
    @patch("todo.views.task.UpdateTaskSerializer")
    def test_patch_task_service_raises_general_value_error(
        self, mock_update_serializer_class, mock_service_update_task
    ):
        valid_payload = {"title": "Update that causes generic service error"}

        mock_serializer_instance = Mock()
        mock_serializer_instance.is_valid.return_value = True
        mock_serializer_instance.validated_data = valid_payload
        mock_update_serializer_class.return_value = mock_serializer_instance

        simulated_service_api_error = ApiErrorResponse(
            statusCode=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ApiErrors.SERVER_ERROR,
            errors=[ApiErrorDetail(detail="Failed to save task updates in service.", title=ApiErrors.UNEXPECTED_ERROR)],
        )
        mock_service_update_task.side_effect = ValueError(simulated_service_api_error)

        response = self.client.patch(self.task_url, data=valid_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["statusCode"], status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["message"], ApiErrors.SERVER_ERROR)
        self.assertEqual(response.data["errors"][0]["detail"], "Failed to save task updates in service.")
        self.assertEqual(response.data["errors"][0]["title"], ApiErrors.UNEXPECTED_ERROR)

    @patch("todo.views.task.TaskService.update_task")
    @patch("todo.views.task.UpdateTaskSerializer")
    def test_patch_task_service_raises_unhandled_exception(
        self, mock_update_serializer_class, mock_service_update_task
    ):
        valid_payload = {"title": "Update that causes unhandled service error"}

        mock_serializer_instance = Mock()
        mock_serializer_instance.is_valid.return_value = True
        mock_serializer_instance.validated_data = valid_payload
        mock_update_serializer_class.return_value = mock_serializer_instance

        mock_service_update_task.side_effect = Exception("Something completely unexpected broke!")

        with patch.object(settings, "DEBUG", False):
            response = self.client.patch(self.task_url, data=valid_payload, format="json")

            self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
            self.assertEqual(response.data["statusCode"], status.HTTP_500_INTERNAL_SERVER_ERROR)
            self.assertEqual(response.data["message"], ApiErrors.INTERNAL_SERVER_ERROR)
            self.assertEqual(response.data["errors"][0]["detail"], ApiErrors.INTERNAL_SERVER_ERROR)

        with patch.object(settings, "DEBUG", True):
            response_debug = self.client.patch(self.task_url, data=valid_payload, format="json")
            self.assertEqual(response_debug.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
            self.assertEqual(response_debug.data["errors"][0]["detail"], "Something completely unexpected broke!")

    @patch("todo.views.task.TaskService.update_task")
    @patch("todo.views.task.UpdateTaskSerializer")
    def test_patch_task_service_raises_exception(self, mock_update_serializer_class, mock_service_update_task):
        mock_service_update_task.side_effect = Exception("A wild error appears!")
        mock_serializer_instance = mock_update_serializer_class.return_value
        mock_serializer_instance.is_valid.return_value = True

        response = self.client.patch(self.task_url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @patch("todo.views.task.DeferTaskSerializer")
    @patch("todo.views.task.TaskService.defer_task")
    def test_patch_task_defer_action_success(self, mock_service_defer_task, mock_defer_serializer_class):
        deferred_till_datetime = datetime.now(timezone.utc) + timedelta(days=5)
        deferred_task_dto = self.updated_task_dto_fixture.model_copy(deep=True)
        deferred_task_dto.deferredDetails = DeferredDetailsDTO(
            deferredAt=datetime.now(timezone.utc),
            deferredTill=deferred_till_datetime,
            deferredBy=UserDTO(id="system_defer_user", name="SYSTEM"),
        )
        mock_service_defer_task.return_value = deferred_task_dto
        mock_serializer_instance = mock_defer_serializer_class.return_value
        mock_serializer_instance.is_valid.return_value = True
        mock_serializer_instance.validated_data = {"deferredTill": deferred_till_datetime}

        url_with_action = f"{self.task_url}?action=defer"
        request_data = {"deferredTill": deferred_till_datetime.isoformat()}
        response = self.client.patch(url_with_action, data=request_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, deferred_task_dto.model_dump(mode="json"))
        mock_defer_serializer_class.assert_called_once_with(data=request_data)
        mock_service_defer_task.assert_called_once_with(
            task_id=self.task_id_str,
            deferred_till=deferred_till_datetime,
            user_id=str(self.user_id),
        )

    @patch("todo.views.task.DeferTaskSerializer")
    def test_patch_task_defer_action_serializer_invalid(self, mock_defer_serializer_class):
        mock_serializer_instance = mock_defer_serializer_class.return_value
        validation_error = DRFValidationError({"deferredTill": ["This field may not be blank."]})
        mock_serializer_instance.is_valid.side_effect = validation_error

        url_with_action = f"{self.task_url}?action=defer"
        response = self.client.patch(url_with_action, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("todo.views.task.TaskService.defer_task")
    @patch("todo.views.task.DeferTaskSerializer")
    def test_patch_task_defer_service_raises_task_not_found(self, mock_defer_serializer_class, mock_service_defer_task):
        deferred_till_datetime = datetime.now(timezone.utc) + timedelta(days=5)
        mock_service_defer_task.side_effect = TaskNotFoundException(self.task_id_str)
        mock_serializer_instance = mock_defer_serializer_class.return_value
        mock_serializer_instance.is_valid.return_value = True
        mock_serializer_instance.validated_data = {"deferredTill": deferred_till_datetime}

        url_with_action = f"{self.task_url}?action=defer"
        response = self.client.patch(
            url_with_action, data={"deferredTill": deferred_till_datetime.isoformat()}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("todo.views.task.TaskService.defer_task")
    @patch("todo.views.task.DeferTaskSerializer")
    def test_patch_task_defer_service_raises_unprocessable_entity(
        self, mock_defer_serializer_class, mock_service_defer_task
    ):
        deferred_till_datetime = datetime.now(timezone.utc) + timedelta(days=5)
        error_message = "Cannot defer too close to due date."
        mock_service_defer_task.side_effect = UnprocessableEntityException(error_message)
        mock_serializer_instance = mock_defer_serializer_class.return_value
        mock_serializer_instance.is_valid.return_value = True
        mock_serializer_instance.validated_data = {"deferredTill": deferred_till_datetime}

        url_with_action = f"{self.task_url}?action=defer"
        response = self.client.patch(
            url_with_action, data={"deferredTill": deferred_till_datetime.isoformat()}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["message"], error_message)

    def test_patch_task_unsupported_action_raises_validation_error(self):
        unsupported_action = "archive"
        url = reverse("task_detail", kwargs={"task_id": self.task_id_str})
        response = self.client.patch(f"{url}?action={unsupported_action}", data={}, format="json")

        expected_detail = ValidationErrors.UNSUPPORTED_ACTION.format(unsupported_action)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["errors"][0]["detail"], expected_detail)


class TaskViewProfileTrueTests(AuthenticatedMongoTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("tasks")

    @patch("todo.services.task_service.TaskService.get_tasks_for_user")
    def test_get_tasks_profile_true_returns_user_tasks(self, mock_get_tasks_for_user):
        mock_get_tasks_for_user.return_value = GetTasksResponse(tasks=[])
        response = self.client.get(self.url + "?profile=true")
        mock_get_tasks_for_user.assert_called_once()
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_tasks_profile_true_requires_auth(self):
        client = APIClient()
        response = client.get(self.url + "?profile=true")
        self.assertEqual(response.status_code, 401)
