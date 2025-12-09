from unittest.mock import Mock, patch, MagicMock
from unittest import TestCase
from django.core.exceptions import ValidationError
from datetime import datetime, timedelta, timezone
from bson import ObjectId

from todo.dto.responses.get_tasks_response import GetTasksResponse
from todo.dto.responses.paginated_response import LinksData
from todo.dto.user_dto import UserDTO
from todo.services.task_service import TaskService, PaginationConfig
from todo.dto.task_dto import TaskDTO
from todo.dto.task_dto import CreateTaskDTO
from todo.tests.fixtures.task import tasks_models
from todo.tests.fixtures.label import label_models
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
from todo.models.task import TaskModel
from todo.exceptions.task_exceptions import (
    TaskNotFoundException,
    UnprocessableEntityException,
    TaskStateConflictException,
)
from bson.errors import InvalidId as BsonInvalidId
from todo.constants.messages import ApiErrors, ValidationErrors
from todo.repositories.task_repository import TaskRepository
from todo.models.label import LabelModel
from todo.models.common.pyobjectid import PyObjectId
from rest_framework.exceptions import ValidationError as DRFValidationError
from todo.tests.integration.base_mongo_test import AuthenticatedMongoTestCase
from todo.exceptions.user_exceptions import UserNotFoundException


class TaskServiceTests(AuthenticatedMongoTestCase):
    @patch("todo.services.task_service.reverse_lazy", return_value="/v1/tasks")
    def setUp(self, mock_reverse_lazy):
        super().setUp()
        self.mock_reverse_lazy = mock_reverse_lazy

    @patch("todo.services.task_service.UserRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.count")
    @patch("todo.services.task_service.TaskRepository.list")
    @patch("todo.services.task_service.LabelRepository.list_by_ids")
    def test_get_tasks_returns_paginated_response(
        self, mock_label_repo: Mock, mock_list: Mock, mock_count: Mock, mock_user_repo: Mock
    ):
        mock_list.return_value = [tasks_models[0]]
        mock_count.return_value = 3
        mock_label_repo.return_value = label_models
        mock_user_repo.return_value = self.get_user_model()

        response: GetTasksResponse = TaskService.get_tasks(
            page=2, limit=1, sort_by="createdAt", order="desc", user_id=str(self.user_id)
        )

        self.assertIsInstance(response, GetTasksResponse)
        self.assertEqual(len(response.tasks), 1)

        self.assertIsInstance(response.links, LinksData)
        self.assertEqual(
            response.links.next, f"{self.mock_reverse_lazy('tasks')}?page=3&limit=1&sort_by=createdAt&order=desc"
        )
        self.assertEqual(
            response.links.prev, f"{self.mock_reverse_lazy('tasks')}?page=1&limit=1&sort_by=createdAt&order=desc"
        )

        mock_list.assert_called_once_with(
            2, 1, "createdAt", "desc", str(self.user_id), team_id=None, status_filter=None
        )
        mock_count.assert_called_once()

    @patch("todo.services.task_service.UserRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.count")
    @patch("todo.services.task_service.TaskRepository.list")
    @patch("todo.services.task_service.LabelRepository.list_by_ids")
    def test_get_tasks_doesnt_returns_prev_link_for_first_page(
        self, mock_label_repo: Mock, mock_list: Mock, mock_count: Mock, mock_user_repo: Mock
    ):
        mock_list.return_value = [tasks_models[0]]
        mock_count.return_value = 2
        mock_label_repo.return_value = label_models
        mock_user_repo.return_value = self.get_user_model()

        response: GetTasksResponse = TaskService.get_tasks(
            page=1, limit=1, sort_by="createdAt", order="desc", user_id=str(self.user_id)
        )

        self.assertIsNotNone(response.links)
        self.assertIsNone(response.links.prev)

        self.assertEqual(
            response.links.next, f"{self.mock_reverse_lazy('tasks')}?page=2&limit=1&sort_by=createdAt&order=desc"
        )

    @patch("todo.services.task_service.TaskRepository.count")
    @patch("todo.services.task_service.TaskRepository.list")
    def test_get_tasks_returns_empty_response_if_no_tasks_present(self, mock_list: Mock, mock_count: Mock):
        mock_list.return_value = []
        mock_count.return_value = 0

        response: GetTasksResponse = TaskService.get_tasks(
            page=1, limit=10, sort_by="createdAt", order="desc", user_id="test_user"
        )

        self.assertIsInstance(response, GetTasksResponse)
        self.assertEqual(len(response.tasks), 0)
        self.assertIsNone(response.links)

        mock_list.assert_called_once_with(1, 10, "createdAt", "desc", "test_user", team_id=None, status_filter=None)
        mock_count.assert_called_once()

    @patch("todo.services.task_service.TaskRepository.count")
    @patch("todo.services.task_service.TaskRepository.list")
    def test_get_tasks_returns_empty_response_when_page_exceeds_range(self, mock_list: Mock, mock_count: Mock):
        mock_list.return_value = []
        mock_count.return_value = 50

        response: GetTasksResponse = TaskService.get_tasks(
            page=999, limit=10, sort_by="createdAt", order="desc", user_id="test_user"
        )

        self.assertIsInstance(response, GetTasksResponse)
        self.assertEqual(len(response.tasks), 0)
        self.assertIsNone(response.links)

    @patch("todo.services.task_service.UserRepository.get_by_id")
    @patch("todo.services.task_service.LabelRepository.list_by_ids")
    def test_prepare_task_dto_maps_model_to_dto(self, mock_label_repo: Mock, mock_user_repo: Mock):
        task_model = tasks_models[0]
        mock_label_repo.return_value = label_models
        mock_user_repo.return_value = self.get_user_model()

        result: TaskDTO = TaskService.prepare_task_dto(task_model)

        mock_label_repo.assert_called_once_with(task_model.labels)

        self.assertIsInstance(result, TaskDTO)
        self.assertEqual(result.id, str(task_model.id))

    @patch("todo.services.task_service.UserRepository.get_by_id")
    def test_prepare_user_dto_maps_model_to_dto(self, mock_user_repo: Mock):
        user_id = self.user_id
        mock_user_repo.return_value = self.get_user_model()

        result: UserDTO = TaskService.prepare_user_dto(user_id)

        self.assertIsInstance(result, UserDTO)
        self.assertEqual(result.id, str(user_id))
        self.assertEqual(result.name, self.user_data["name"])

    def test_validate_pagination_params_with_valid_params(self):
        TaskService._validate_pagination_params(1, 10)

    def test_validate_pagination_params_with_invalid_page(self):
        with self.assertRaises(ValidationError) as context:
            TaskService._validate_pagination_params(0, 10)
        self.assertIn("Page must be a positive integer", str(context.exception))

    def test_validate_pagination_params_with_invalid_limit(self):
        with self.assertRaises(ValidationError) as context:
            TaskService._validate_pagination_params(1, 0)
        self.assertIn("Limit must be a positive integer", str(context.exception))

        with self.assertRaises(ValidationError) as context:
            TaskService._validate_pagination_params(1, PaginationConfig.MAX_LIMIT + 1)
        self.assertIn(f"Maximum limit of {PaginationConfig.MAX_LIMIT}", str(context.exception))

    @patch("todo.services.task_service.UserRepository.get_by_id")
    def test_prepare_label_dtos_converts_ids_to_dtos(self, mock_user_repo: Mock):
        label_ids = ["label_id_1", "label_id_2"]
        mock_user_repo.return_value = self.get_user_model()

        with patch("todo.services.task_service.LabelRepository.list_by_ids") as mock_list_by_ids:
            mock_list_by_ids.return_value = label_models

            result = TaskService._prepare_label_dtos(label_ids)

            self.assertEqual(len(result), len(label_models))
            self.assertEqual(result[0].name, label_models[0].name)
            self.assertEqual(result[0].color, label_models[0].color)

            mock_list_by_ids.assert_called_once_with(label_ids)

    def test_get_tasks_handles_validation_error(self):
        with patch("todo.services.task_service.TaskService._validate_pagination_params") as mock_validate:
            mock_validate.side_effect = ValidationError("Test validation error")

            response = TaskService.get_tasks(page=1, limit=10, sort_by="createdAt", order="desc", user_id="test_user")

            self.assertIsInstance(response, GetTasksResponse)
            self.assertEqual(len(response.tasks), 0)
            self.assertIsNone(response.links)

    @patch("todo.services.task_service.TaskRepository.list")
    def test_get_tasks_handles_general_exception(self, mock_list: Mock):
        mock_list.side_effect = Exception("Test general error")

        response = TaskService.get_tasks(page=1, limit=10, sort_by="createdAt", order="desc", user_id="test_user")

        self.assertIsInstance(response, GetTasksResponse)
        self.assertEqual(len(response.tasks), 0)
        self.assertIsNone(response.links)

    @patch("todo.services.task_service.TaskRepository.create")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    @patch("todo.services.task_service.TaskAssignmentService.create_task_assignment")
    @patch("todo.services.task_service.UserRepository.get_by_id")
    @patch("todo.services.task_service.TeamRepository.get_by_id")
    def test_create_task_with_user_assignment_and_team_id(
        self, mock_team_repo, mock_user_repo, mock_create_assignment, mock_prepare_dto, mock_create
    ):
        team_id = str(ObjectId())
        user_id = str(ObjectId())

        dto = CreateTaskDTO(
            title="Test Task",
            description="This is a test",
            priority=TaskPriority.HIGH,
            status=TaskStatus.TODO,
            assignee={"assignee_id": user_id, "user_type": "user", "team_id": team_id},
            createdBy=str(self.user_id),
            labels=[],
            dueAt=datetime.now(timezone.utc) + timedelta(days=1),
        )

        mock_user_repo.return_value = MagicMock()
        mock_team_repo.return_value = MagicMock()

        mock_task_model = MagicMock(spec=TaskModel)
        mock_task_model.id = ObjectId()
        mock_task_model.createdBy = str(self.user_id)
        mock_create.return_value = mock_task_model
        mock_task_dto = MagicMock(spec=TaskDTO)
        mock_prepare_dto.return_value = mock_task_dto

        mock_assignment_response = MagicMock()
        mock_assignment_response.data.task_id = str(mock_task_model.id)
        mock_assignment_response.data.assignee_id = user_id
        mock_create_assignment.return_value = mock_assignment_response

        result = TaskService.create_task(dto)

        mock_create.assert_called_once()

        mock_create_assignment.assert_called_once()
        assignment_call_args = mock_create_assignment.call_args[0][0]
        self.assertEqual(assignment_call_args.task_id, str(mock_task_model.id))
        self.assertEqual(assignment_call_args.assignee_id, user_id)
        self.assertEqual(assignment_call_args.user_type, "user")
        self.assertEqual(assignment_call_args.team_id, team_id)

        mock_prepare_dto.assert_called_once_with(mock_task_model, str(self.user_id))
        self.assertEqual(result.data, mock_task_dto)

    @patch("todo.services.task_service.TaskRepository.create")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    @patch("todo.services.task_service.TaskAssignmentService.create_task_assignment")
    @patch("todo.services.task_service.UserRepository.get_by_id")
    def test_create_task_with_user_assignment_without_team_id(
        self, mock_user_repo, mock_create_assignment, mock_prepare_dto, mock_create
    ):
        user_id = str(ObjectId())

        dto = CreateTaskDTO(
            title="Test Task",
            description="This is a test",
            priority=TaskPriority.HIGH,
            status=TaskStatus.TODO,
            assignee={"assignee_id": user_id, "user_type": "user"},
            createdBy=str(self.user_id),
            labels=[],
            dueAt=datetime.now(timezone.utc) + timedelta(days=1),
        )

        mock_user_repo.return_value = MagicMock()

        mock_task_model = MagicMock(spec=TaskModel)
        mock_task_model.id = ObjectId()
        mock_task_model.createdBy = str(self.user_id)
        mock_create.return_value = mock_task_model
        mock_task_dto = MagicMock(spec=TaskDTO)
        mock_prepare_dto.return_value = mock_task_dto

        TaskService.create_task(dto)

        mock_create_assignment.assert_called_once()
        assignment_call_args = mock_create_assignment.call_args[0][0]
        self.assertEqual(assignment_call_args.task_id, str(mock_task_model.id))
        self.assertEqual(assignment_call_args.assignee_id, user_id)
        self.assertEqual(assignment_call_args.user_type, "user")
        self.assertIsNone(assignment_call_args.team_id)

    @patch("todo.services.task_service.TaskRepository.create")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    @patch("todo.services.task_service.TaskAssignmentService.create_task_assignment")
    @patch("todo.services.task_service.UserRepository.get_by_id")
    @patch("todo.services.task_service.TeamRepository.get_by_id")
    def test_create_task_validates_team_exists_for_user_assignment(
        self, mock_team_repo, mock_user_repo, mock_create_assignment, mock_prepare_dto, mock_create
    ):
        team_id = str(ObjectId())
        user_id = str(ObjectId())

        dto = CreateTaskDTO(
            title="Test Task",
            description="This is a test",
            priority=TaskPriority.HIGH,
            status=TaskStatus.TODO,
            assignee={"assignee_id": user_id, "user_type": "user", "team_id": team_id},
            createdBy=str(self.user_id),
            labels=[],
            dueAt=datetime.now(timezone.utc) + timedelta(days=1),
        )

        mock_user_repo.return_value = MagicMock()
        mock_team_repo.return_value = None  # Team not found

        with self.assertRaises(ValueError) as context:
            TaskService.create_task(dto)

        self.assertIn(f"Team not found: {team_id}", str(context.exception))
        mock_team_repo.assert_called_once_with(team_id)

    @patch("todo.services.task_service.TaskRepository.create")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    @patch("todo.services.task_service.TaskAssignmentService.create_task_assignment")
    @patch("todo.services.task_service.UserRepository.get_by_id")
    @patch("todo.services.task_service.TeamRepository.get_by_id")
    def test_create_task_passes_team_id_to_assignment_service(
        self, mock_team_repo, mock_user_repo, mock_create_assignment, mock_prepare_dto, mock_create
    ):
        team_id = str(ObjectId())
        user_id = str(ObjectId())

        dto = CreateTaskDTO(
            title="Test Task",
            description="This is a test",
            priority=TaskPriority.HIGH,
            status=TaskStatus.TODO,
            assignee={"assignee_id": user_id, "user_type": "user", "team_id": team_id},
            createdBy=str(self.user_id),
            labels=[],
            dueAt=datetime.now(timezone.utc) + timedelta(days=1),
        )

        mock_user_repo.return_value = MagicMock()
        mock_team_repo.return_value = MagicMock()

        mock_task_model = MagicMock(spec=TaskModel)
        mock_task_model.id = ObjectId()
        mock_task_model.createdBy = str(self.user_id)
        mock_create.return_value = mock_task_model
        mock_task_dto = MagicMock(spec=TaskDTO)
        mock_prepare_dto.return_value = mock_task_dto

        mock_assignment_response = MagicMock()
        mock_assignment_response.data.task_id = str(mock_task_model.id)
        mock_assignment_response.data.assignee_id = user_id
        mock_create_assignment.return_value = mock_assignment_response

        TaskService.create_task(dto)

        mock_create_assignment.assert_called_once()
        assignment_call_args = mock_create_assignment.call_args[0][0]
        self.assertEqual(assignment_call_args.team_id, team_id)
        self.assertEqual(assignment_call_args.assignee_id, user_id)
        self.assertEqual(assignment_call_args.user_type, "user")

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_get_task_by_id_success(self, mock_prepare_task_dto: Mock, mock_repo_get_by_id: Mock):
        task_id = "validtaskid123"
        mock_task_model = MagicMock(spec=TaskModel)
        mock_repo_get_by_id.return_value = mock_task_model

        mock_dto = MagicMock(spec=TaskDTO)
        mock_prepare_task_dto.return_value = mock_dto

        result_dto = TaskService.get_task_by_id(task_id)

        mock_repo_get_by_id.assert_called_once_with(task_id)
        mock_prepare_task_dto.assert_called_once_with(mock_task_model, user_id=None)
        self.assertEqual(result_dto, mock_dto)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    def test_get_task_by_id_raises_task_not_found(self, mock_repo_get_by_id: Mock):
        mock_repo_get_by_id.return_value = None
        task_id = "6833661c84e8da308f27e0d55"
        expected_message = ApiErrors.TASK_NOT_FOUND.format(task_id)

        with self.assertRaises(TaskNotFoundException) as context:
            TaskService.get_task_by_id(task_id)

        self.assertEqual(str(context.exception), expected_message)
        mock_repo_get_by_id.assert_called_once_with(task_id)

    @patch.object(TaskRepository, "get_by_id", side_effect=BsonInvalidId("Invalid ObjectId"))
    def test_get_task_by_id_invalid_id_format(self, mock_get_by_id_repo_method: Mock):
        invalid_id = "invalid_id_format"

        with self.assertRaises(BsonInvalidId) as context:
            TaskService.get_task_by_id(invalid_id)

        self.assertEqual(str(context.exception), "Invalid ObjectId")
        mock_get_by_id_repo_method.assert_called_once_with(invalid_id)

    @patch("todo.services.task_service.TaskRepository.delete_by_id")
    def test_delete_task_success(self, mock_delete_by_id):
        mock_delete_by_id.return_value = {"id": "123", "title": "Sample Task"}
        result = TaskService.delete_task("123", str(self.user_id))
        self.assertIsNone(result)

    @patch("todo.services.task_service.TaskRepository.delete_by_id")
    def test_delete_task_not_found(self, mock_delete_by_id):
        mock_delete_by_id.return_value = None
        with self.assertRaises(TaskNotFoundException):
            TaskService.delete_task("nonexistent_id", str(self.user_id))


class TaskServiceSortingTests(TestCase):
    @patch("todo.services.task_service.TaskRepository.count")
    @patch("todo.services.task_service.TaskRepository.list")
    def test_get_tasks_default_sorting(self, mock_list, mock_count):
        mock_list.return_value = []
        mock_count.return_value = 0

        TaskService.get_tasks(page=1, limit=20, sort_by="createdAt", order="desc", user_id="test_user")

        mock_list.assert_called_once_with(
            1, 20, SORT_FIELD_CREATED_AT, SORT_ORDER_DESC, "test_user", team_id=None, status_filter=None
        )

    @patch("todo.services.task_service.TaskRepository.count")
    @patch("todo.services.task_service.TaskRepository.list")
    def test_get_tasks_explicit_sort_by_priority(self, mock_list, mock_count):
        mock_list.return_value = []
        mock_count.return_value = 0

        TaskService.get_tasks(page=1, limit=20, sort_by=SORT_FIELD_PRIORITY, order=SORT_ORDER_DESC, user_id="test_user")

        mock_list.assert_called_once_with(
            1, 20, SORT_FIELD_PRIORITY, SORT_ORDER_DESC, "test_user", team_id=None, status_filter=None
        )

    @patch("todo.services.task_service.TaskRepository.count")
    @patch("todo.services.task_service.TaskRepository.list")
    def test_get_tasks_sort_by_due_at_default_order(self, mock_list, mock_count):
        mock_list.return_value = []
        mock_count.return_value = 0

        TaskService.get_tasks(page=1, limit=20, sort_by=SORT_FIELD_DUE_AT, order="asc", user_id="test_user")

        mock_list.assert_called_once_with(
            1, 20, SORT_FIELD_DUE_AT, SORT_ORDER_ASC, "test_user", team_id=None, status_filter=None
        )

    @patch("todo.services.task_service.TaskRepository.count")
    @patch("todo.services.task_service.TaskRepository.list")
    def test_get_tasks_sort_by_priority_default_order(self, mock_list, mock_count):
        mock_list.return_value = []
        mock_count.return_value = 0

        TaskService.get_tasks(page=1, limit=20, sort_by=SORT_FIELD_PRIORITY, order="desc", user_id="test_user")

        mock_list.assert_called_once_with(
            1, 20, SORT_FIELD_PRIORITY, SORT_ORDER_DESC, "test_user", team_id=None, status_filter=None
        )

    @patch("todo.services.task_service.TaskRepository.count")
    @patch("todo.services.task_service.TaskRepository.list")
    def test_get_tasks_sort_by_assignee_default_order(self, mock_list, mock_count):
        mock_list.return_value = []
        mock_count.return_value = 0

        TaskService.get_tasks(page=1, limit=20, sort_by=SORT_FIELD_ASSIGNEE, order="asc", user_id="test_user")

        mock_list.assert_called_once_with(
            1, 20, SORT_FIELD_ASSIGNEE, SORT_ORDER_ASC, "test_user", team_id=None, status_filter=None
        )

    @patch("todo.services.task_service.TaskRepository.count")
    @patch("todo.services.task_service.TaskRepository.list")
    def test_get_tasks_sort_by_created_at_default_order(self, mock_list, mock_count):
        mock_list.return_value = []
        mock_count.return_value = 0

        TaskService.get_tasks(page=1, limit=20, sort_by=SORT_FIELD_CREATED_AT, order="desc", user_id="test_user")

        mock_list.assert_called_once_with(
            1, 20, SORT_FIELD_CREATED_AT, SORT_ORDER_DESC, "test_user", team_id=None, status_filter=None
        )

    @patch("todo.services.task_service.reverse_lazy", return_value="/v1/tasks")
    def test_build_page_url_includes_sort_parameters(self, mock_reverse):
        url = TaskService.build_page_url(2, 10, SORT_FIELD_PRIORITY, SORT_ORDER_DESC)

        expected_url = "/v1/tasks?page=2&limit=10&sort_by=priority&order=desc"
        self.assertEqual(url, expected_url)

    @patch("todo.services.task_service.reverse_lazy", return_value="/v1/tasks")
    def test_build_page_url_with_default_sort_parameters(self, mock_reverse):
        url = TaskService.build_page_url(1, 20, SORT_FIELD_DUE_AT, "asc")

        expected_url = "/v1/tasks?page=1&limit=20&sort_by=dueAt&order=asc"
        self.assertEqual(url, expected_url)

    @patch("todo.services.task_service.TaskRepository.count")
    @patch("todo.services.task_service.TaskRepository.list")
    def test_get_tasks_pagination_links_preserve_sort_params(self, mock_list, mock_count):
        """Test that pagination links preserve sort parameters"""
        from todo.tests.fixtures.task import tasks_models

        mock_user = MagicMock()
        mock_user.name = "Test User"

        mock_list.return_value = [tasks_models[0]]
        mock_count.return_value = 3

        with (
            patch("todo.services.task_service.LabelRepository.list_by_ids", return_value=[]),
            patch("todo.services.task_service.UserRepository.get_by_id", return_value=mock_user),
            patch("todo.services.task_service.reverse_lazy", return_value="/v1/tasks"),
        ):
            response = TaskService.get_tasks(
                page=2, limit=1, sort_by=SORT_FIELD_PRIORITY, order=SORT_ORDER_DESC, user_id="test_user"
            )

            self.assertIsNotNone(response.links)
            self.assertIn("sort_by=priority", response.links.next)
            self.assertIn("order=desc", response.links.next)
            self.assertIn("sort_by=priority", response.links.prev)
            self.assertIn("order=desc", response.links.prev)


class TaskServiceUpdateTests(TestCase):
    def setUp(self):
        self.task_id_str = str(ObjectId())
        self.user_id_str = str(ObjectId())
        self.default_task_model = TaskModel(
            id=ObjectId(self.task_id_str),
            displayId="#TSK1",
            title="Original Task Title",
            description="Original Description",
            priority=TaskPriority.MEDIUM,
            status=TaskStatus.TODO,
            createdBy=self.user_id_str,
            createdAt=datetime.now(timezone.utc) - timedelta(days=2),
        )
        self.label_id_1_str = str(ObjectId())
        self.label_id_2_str = str(ObjectId())
        self.mock_label_1 = LabelModel(
            id=PyObjectId(self.label_id_1_str),
            name="Label One",
            color="#FF0000",
            createdBy="system",
            createdAt=datetime.now(timezone.utc),
        )
        self.mock_label_2 = LabelModel(
            id=PyObjectId(self.label_id_2_str),
            name="Label Two",
            color="#00FF00",
            createdBy="system",
            createdAt=datetime.now(timezone.utc),
        )


@patch("todo.services.task_service.UserRepository.get_by_id")
@patch("todo.services.task_service.TaskRepository.get_by_id")
@patch("todo.services.task_service.TaskRepository.update")
@patch("todo.services.task_service.LabelRepository.list_by_ids")
@patch("todo.services.task_service.TaskService.prepare_task_dto")
def test_update_task_success_full_payload(
    mock_prepare_dto,
    mock_list_labels,
    mock_repo_update,
    mock_repo_get_by_id,
    mock_user_get_by_id,
):
    user_id_str = str(ObjectId())
    task_id_str = str(ObjectId())
    label_id_1_str = str(ObjectId())

    mock_user_get_by_id.return_value = MagicMock()

    default_task_model = MagicMock(spec=TaskModel)
    mock_repo_get_by_id.return_value = default_task_model

    updated_task_model_from_repo = default_task_model.model_copy(deep=True)
    updated_task_model_from_repo.title = "Updated Title via Service"
    updated_task_model_from_repo.status = TaskStatus.IN_PROGRESS
    updated_task_model_from_repo.priority = TaskPriority.HIGH
    updated_task_model_from_repo.description = "New Description"
    # Remove assignee from task model since it's now in separate collection
    updated_task_model_from_repo.dueAt = datetime.now(timezone.utc) + timedelta(days=5)
    updated_task_model_from_repo.startedAt = datetime.now(timezone.utc) - timedelta(hours=2)
    updated_task_model_from_repo.isAcknowledged = True
    updated_task_model_from_repo.labels = [PyObjectId(label_id_1_str)]
    updated_task_model_from_repo.updatedBy = user_id_str
    updated_task_model_from_repo.updatedAt = datetime.now(timezone.utc)

    mock_repo_update.return_value = updated_task_model_from_repo

    mock_dto_response = MagicMock(spec=TaskDTO)
    mock_prepare_dto.return_value = mock_dto_response

    mock_label = MagicMock()
    mock_list_labels.return_value = [mock_label]

    validated_data_from_serializer = {
        "title": "Updated Title via Service",
        "description": "New Description",
        "priority": TaskPriority.HIGH.name,
        "status": TaskStatus.IN_PROGRESS.name,
        "assignee": {"assignee_id": user_id_str, "user_type": "user"},
        "labels": [label_id_1_str],
        "dueAt": updated_task_model_from_repo.dueAt,
        "startedAt": updated_task_model_from_repo.startedAt,
        "isAcknowledged": True,
    }

    result_dto = TaskService.update_task(task_id_str, validated_data_from_serializer, user_id_str)

    mock_repo_get_by_id.assert_called_once_with(task_id_str)
    mock_list_labels.assert_called_once_with([PyObjectId(label_id_1_str)])
    mock_repo_update.assert_called_once()
    update_payload = mock_repo_update.call_args[0][1]

    assert update_payload["title"] == validated_data_from_serializer["title"]
    assert update_payload["status"] == TaskStatus.IN_PROGRESS.value
    assert update_payload["priority"] == TaskPriority.HIGH.value
    assert update_payload["description"] == validated_data_from_serializer["description"]
    # Remove assignee from payload since it's handled separately
    assert update_payload["dueAt"] == validated_data_from_serializer["dueAt"]
    assert update_payload["startedAt"] == validated_data_from_serializer["startedAt"]
    assert update_payload["isAcknowledged"] == validated_data_from_serializer["isAcknowledged"]
    assert update_payload["labels"] == [PyObjectId(label_id_1_str)]
    assert update_payload["updatedBy"] == user_id_str

    mock_prepare_dto.assert_called_once_with(updated_task_model_from_repo)
    assert result_dto == mock_dto_response

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_update_task_no_actual_changes_returns_current_task_dto(
        self, mock_prepare_dto, mock_repo_update, mock_repo_get_by_id
    ):
        mock_repo_get_by_id.return_value = self.default_task_model
        mock_dto_response = MagicMock(spec=TaskDTO)
        mock_prepare_dto.return_value = mock_dto_response

        validated_data_empty = {}
        result_dto = TaskService.update_task(self.task_id_str, validated_data_empty, self.user_id_str)

        mock_repo_get_by_id.assert_called_once_with(self.task_id_str)
        mock_repo_update.assert_not_called()
        mock_prepare_dto.assert_called_once_with(self.default_task_model)
        self.assertEqual(result_dto, mock_dto_response)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    def test_update_task_raises_task_not_found(self, mock_repo_get_by_id):
        mock_repo_get_by_id.return_value = None
        validated_data = {"title": "some update"}

        with self.assertRaises(TaskNotFoundException) as context:
            TaskService.update_task(self.task_id_str, validated_data, self.user_id_str)

        self.assertEqual(str(context.exception), ApiErrors.TASK_NOT_FOUND.format(self.task_id_str))
        mock_repo_get_by_id.assert_called_once_with(self.task_id_str)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.LabelRepository.list_by_ids")
    def test_update_task_raises_drf_validation_error_for_missing_labels(self, mock_list_labels, mock_repo_get_by_id):
        mock_repo_get_by_id.return_value = self.default_task_model
        mock_list_labels.return_value = [self.mock_label_1]

        label_id_non_existent = str(ObjectId())
        validated_data_with_bad_label = {"labels": [self.label_id_1_str, label_id_non_existent]}

        with self.assertRaises(DRFValidationError) as context:
            TaskService.update_task(self.task_id_str, validated_data_with_bad_label, self.user_id_str)

        self.assertIn("labels", context.exception.detail)
        self.assertIn(
            ValidationErrors.MISSING_LABEL_IDS.format(label_id_non_existent), context.exception.detail["labels"]
        )
        mock_repo_get_by_id.assert_called_once_with(self.task_id_str)
        mock_list_labels.assert_called_once_with([PyObjectId(self.label_id_1_str), PyObjectId(label_id_non_existent)])

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    def test_update_task_raises_task_not_found_if_repo_update_fails(self, mock_repo_update, mock_repo_get_by_id):
        mock_repo_get_by_id.return_value = self.default_task_model
        mock_repo_update.return_value = None

        validated_data = {"title": "Updated Title"}

        with self.assertRaises(TaskNotFoundException) as context:
            TaskService.update_task(self.task_id_str, validated_data, self.user_id_str)

        self.assertEqual(str(context.exception), ApiErrors.TASK_NOT_FOUND.format(self.task_id_str))
        mock_repo_get_by_id.assert_called_once_with(self.task_id_str)
        mock_repo_update.assert_called_once_with(self.task_id_str, {**validated_data, "updatedBy": self.user_id_str})

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_update_task_clears_labels_when_labels_is_none(
        self, mock_prepare_dto, mock_repo_update, mock_repo_get_by_id
    ):
        mock_repo_get_by_id.return_value = self.default_task_model
        updated_task_model_from_repo = self.default_task_model.model_copy(deep=True)
        updated_task_model_from_repo.labels = []
        mock_repo_update.return_value = updated_task_model_from_repo
        mock_prepare_dto.return_value = MagicMock(spec=TaskDTO)

        validated_data = {"labels": None}
        TaskService.update_task(self.task_id_str, validated_data, self.user_id_str)

        _, kwargs_update = mock_repo_update.call_args
        update_payload = mock_repo_update.call_args[0][1]
        self.assertEqual(update_payload["labels"], [])

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.LabelRepository.list_by_ids")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_update_task_sets_empty_labels_list_when_labels_is_empty_list(
        self, mock_prepare_dto, mock_list_labels, mock_repo_update, mock_repo_get_by_id
    ):
        mock_repo_get_by_id.return_value = self.default_task_model
        updated_task_model_from_repo = self.default_task_model.model_copy(deep=True)
        updated_task_model_from_repo.labels = []
        mock_repo_update.return_value = updated_task_model_from_repo
        mock_prepare_dto.return_value = MagicMock(spec=TaskDTO)
        mock_list_labels.return_value = []

        validated_data = {"labels": []}
        TaskService.update_task(self.task_id_str, validated_data, self.user_id_str)

        update_payload_sent_to_repo = mock_repo_update.call_args[0][1]
        self.assertEqual(update_payload_sent_to_repo["labels"], [])
        mock_list_labels.assert_not_called()

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_update_task_converts_priority_and_status_names_to_values(
        self, mock_prepare_dto, mock_repo_update, mock_repo_get_by_id
    ):
        mock_repo_get_by_id.return_value = self.default_task_model
        updated_task_model_from_repo = self.default_task_model.model_copy(deep=True)
        mock_repo_update.return_value = updated_task_model_from_repo
        mock_prepare_dto.return_value = MagicMock(spec=TaskDTO)

        validated_data = {"priority": TaskPriority.LOW.name, "status": TaskStatus.DONE.name}
        TaskService.update_task(self.task_id_str, validated_data, self.user_id_str)

        update_payload_sent_to_repo = mock_repo_update.call_args[0][1]
        self.assertEqual(update_payload_sent_to_repo["priority"], TaskPriority.LOW.value)
        self.assertEqual(update_payload_sent_to_repo["status"], TaskStatus.DONE.value)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_update_task_handles_null_priority_and_status(
        self, mock_prepare_dto, mock_repo_update, mock_repo_get_by_id
    ):
        mock_repo_get_by_id.return_value = self.default_task_model
        updated_task_model_from_repo = self.default_task_model.model_copy(deep=True)
        mock_repo_update.return_value = updated_task_model_from_repo
        mock_prepare_dto.return_value = MagicMock(spec=TaskDTO)

        validated_data = {"priority": None, "status": None}
        TaskService.update_task(self.task_id_str, validated_data, self.user_id_str)

        update_payload_sent_to_repo = mock_repo_update.call_args[0][1]
        self.assertIsNone(update_payload_sent_to_repo["priority"])
        self.assertIsNone(update_payload_sent_to_repo["status"])

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskRepository._get_assigned_task_ids_for_user")
    def test_update_task_permission_denied_if_not_creator_or_assignee(
        self, mock_get_assigned, mock_update, mock_get_by_id
    ):
        task_id = self.task_id_str
        user_id = "not_creator_or_assignee"
        task_model = self.default_task_model.model_copy(deep=True)
        task_model.createdBy = "some_other_user"
        mock_get_by_id.return_value = task_model
        mock_get_assigned.return_value = []
        validated_data = {"title": "new title"}
        with self.assertRaises(PermissionError) as context:
            TaskService.update_task(task_id, validated_data, user_id)
        self.assertEqual(str(context.exception), ApiErrors.UNAUTHORIZED_TITLE)
        mock_get_by_id.assert_called_once_with(task_id)
        mock_get_assigned.assert_called_once_with(user_id)
        mock_update.assert_not_called()

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskRepository._get_assigned_task_ids_for_user")
    def test_update_task_permission_allowed_if_assignee(self, mock_get_assigned, mock_update, mock_get_by_id):
        task_id = self.task_id_str
        user_id = "assignee_user"
        task_model = self.default_task_model.model_copy(deep=True)
        task_model.createdBy = "some_other_user"
        mock_get_by_id.return_value = task_model
        mock_get_assigned.return_value = [task_model.id]
        mock_update.return_value = task_model
        validated_data = {"title": "new title"}
        TaskService.update_task(task_id, validated_data, user_id)
        mock_get_by_id.assert_called_once_with(task_id)
        mock_get_assigned.assert_called_once_with(user_id)
        mock_update.assert_called_once()


class TaskServiceUpdateWithAssigneeTests(TestCase):
    def setUp(self):
        self.task_id_str = str(ObjectId())
        self.user_id_str = str(ObjectId())
        self.assignee_id_str = str(ObjectId())
        self.default_task_model = TaskModel(
            id=ObjectId(self.task_id_str),
            displayId="#TSK1",
            title="Original Task Title",
            description="Original Description",
            priority=TaskPriority.MEDIUM,
            status=TaskStatus.TODO,
            createdBy=self.user_id_str,
            createdAt=datetime.now(timezone.utc) - timedelta(days=2),
        )

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskAssignmentRepository.update_assignment")
    @patch("todo.services.task_service.UserRepository.get_by_id")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_update_task_with_assignee_success(
        self, mock_prepare_dto, mock_user_get_by_id, mock_update_assignment, mock_repo_update, mock_repo_get_by_id
    ):
        mock_user_get_by_id.return_value = MagicMock()
        mock_repo_get_by_id.return_value = self.default_task_model

        updated_task_model = self.default_task_model.model_copy(deep=True)
        updated_task_model.title = "Updated Title"
        updated_task_model.status = TaskStatus.IN_PROGRESS
        mock_repo_update.return_value = updated_task_model

        mock_update_assignment.return_value = MagicMock()

        mock_dto_response = MagicMock(spec=TaskDTO)
        mock_prepare_dto.return_value = mock_dto_response

        # Create DTO with task and assignee updates
        dto = CreateTaskDTO(
            title="Updated Title",
            status=TaskStatus.IN_PROGRESS.name,
            assignee={"assignee_id": self.assignee_id_str, "user_type": "user"},
            createdBy=self.user_id_str,
        )

        result_dto = TaskService.update_task_with_assignee(self.task_id_str, dto, self.user_id_str)

        mock_repo_get_by_id.assert_called_once_with(self.task_id_str)
        mock_user_get_by_id.assert_called_once_with(self.assignee_id_str)
        mock_repo_update.assert_called_once()
        mock_update_assignment.assert_called_once_with(self.task_id_str, self.assignee_id_str, "user", self.user_id_str)
        mock_prepare_dto.assert_called_once_with(updated_task_model, self.user_id_str)

        self.assertEqual(result_dto, mock_dto_response)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskAssignmentRepository.update_assignment")
    @patch("todo.services.task_service.TeamRepository.get_by_id")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_update_task_with_team_assignee_success(
        self, mock_prepare_dto, mock_team_get_by_id, mock_update_assignment, mock_repo_update, mock_repo_get_by_id
    ):
        mock_team_get_by_id.return_value = MagicMock()
        mock_repo_get_by_id.return_value = self.default_task_model

        updated_task_model = self.default_task_model.model_copy(deep=True)
        updated_task_model.title = "Updated Title"
        mock_repo_update.return_value = updated_task_model

        mock_update_assignment.return_value = MagicMock()

        mock_dto_response = MagicMock(spec=TaskDTO)
        mock_prepare_dto.return_value = mock_dto_response

        # Create DTO with team assignee
        dto = CreateTaskDTO(
            title="Updated Title",
            assignee={"assignee_id": self.assignee_id_str, "user_type": "team"},
            createdBy=self.user_id_str,
        )

        result_dto = TaskService.update_task_with_assignee(self.task_id_str, dto, self.user_id_str)

        mock_team_get_by_id.assert_called_once_with(self.assignee_id_str)
        mock_update_assignment.assert_called_once_with(self.task_id_str, self.assignee_id_str, "team", self.user_id_str)

        self.assertEqual(result_dto, mock_dto_response)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    def test_update_task_with_assignee_task_not_found(self, mock_repo_get_by_id):
        mock_repo_get_by_id.return_value = None

        dto = CreateTaskDTO(title="Updated Title", createdBy=self.user_id_str)

        with self.assertRaises(TaskNotFoundException) as context:
            TaskService.update_task_with_assignee(self.task_id_str, dto, self.user_id_str)

        self.assertEqual(str(context.exception), ApiErrors.TASK_NOT_FOUND.format(self.task_id_str))

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository._get_assigned_task_ids_for_user")
    def test_update_task_with_assignee_permission_denied(self, mock_get_assigned, mock_repo_get_by_id):
        task_model = self.default_task_model.model_copy(deep=True)
        task_model.createdBy = "different_user"
        mock_repo_get_by_id.return_value = task_model
        mock_get_assigned.return_value = []

        dto = CreateTaskDTO(title="Updated Title", createdBy=self.user_id_str)

        with self.assertRaises(PermissionError) as context:
            TaskService.update_task_with_assignee(self.task_id_str, dto, self.user_id_str)

        self.assertEqual(str(context.exception), ApiErrors.UNAUTHORIZED_TITLE)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.UserRepository.get_by_id")
    def test_update_task_with_assignee_user_not_found(self, mock_user_get_by_id, mock_repo_get_by_id):
        mock_repo_get_by_id.return_value = self.default_task_model
        mock_user_get_by_id.return_value = None

        dto = CreateTaskDTO(
            title="Test Title",
            assignee={"assignee_id": self.assignee_id_str, "user_type": "user"},
            createdBy=self.user_id_str,
        )

        with self.assertRaises(UserNotFoundException) as context:
            TaskService.update_task_with_assignee(self.task_id_str, dto, self.user_id_str)

        self.assertEqual(str(context.exception), ApiErrors.USER_NOT_FOUND.format(self.assignee_id_str))

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TeamRepository.get_by_id")
    def test_update_task_with_assignee_team_not_found(self, mock_team_get_by_id, mock_repo_get_by_id):
        mock_repo_get_by_id.return_value = self.default_task_model
        mock_team_get_by_id.return_value = None

        dto = CreateTaskDTO(
            title="Test Title",
            assignee={"assignee_id": self.assignee_id_str, "user_type": "team"},
            createdBy=self.user_id_str,
        )

        with self.assertRaises(ValueError) as context:
            TaskService.update_task_with_assignee(self.task_id_str, dto, self.user_id_str)

        self.assertEqual(str(context.exception), f"Team not found: {self.assignee_id_str}")

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_update_task_with_assignee_started_at_logic(self, mock_prepare_dto, mock_repo_update, mock_repo_get_by_id):
        mock_repo_get_by_id.return_value = self.default_task_model

        updated_task_model = self.default_task_model.model_copy(deep=True)
        updated_task_model.startedAt = datetime.now(timezone.utc)
        mock_repo_update.return_value = updated_task_model

        mock_dto_response = MagicMock(spec=TaskDTO)
        mock_prepare_dto.return_value = mock_dto_response

        # DTO with IN_PROGRESS status
        dto = CreateTaskDTO(
            title="Test Title",
            status=TaskStatus.IN_PROGRESS.name,
            createdBy=self.user_id_str,
        )

        result_dto = TaskService.update_task_with_assignee(self.task_id_str, dto, self.user_id_str)

        # Check that startedAt was set in the update payload
        update_payload = mock_repo_update.call_args[0][1]
        self.assertIn("startedAt", update_payload)
        self.assertIsInstance(update_payload["startedAt"], datetime)

        self.assertEqual(result_dto, mock_dto_response)


class TaskServiceUpdateWithAssigneeFromDictTests(TestCase):
    def setUp(self):
        self.task_id_str = str(ObjectId())
        self.user_id_str = str(ObjectId())
        self.assignee_id_str = str(ObjectId())
        self.default_task_model = TaskModel(
            id=ObjectId(self.task_id_str),
            displayId="#TSK1",
            title="Original Task Title",
            description="Original Description",
            priority=TaskPriority.MEDIUM,
            status=TaskStatus.TODO,
            createdBy=self.user_id_str,
            createdAt=datetime.now(timezone.utc) - timedelta(days=2),
        )

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskAssignmentRepository.update_assignment")
    @patch("todo.services.task_service.UserRepository.get_by_id")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_update_task_with_assignee_from_dict_success(
        self, mock_prepare_dto, mock_user_get_by_id, mock_update_assignment, mock_repo_update, mock_repo_get_by_id
    ):
        mock_user_get_by_id.return_value = MagicMock()
        mock_repo_get_by_id.return_value = self.default_task_model

        updated_task_model = self.default_task_model.model_copy(deep=True)
        updated_task_model.title = "Updated Title"
        updated_task_model.status = TaskStatus.IN_PROGRESS
        mock_repo_update.return_value = updated_task_model

        mock_update_assignment.return_value = MagicMock()

        mock_dto_response = MagicMock(spec=TaskDTO)
        mock_prepare_dto.return_value = mock_dto_response

        # Validated data with task and assignee updates
        validated_data = {
            "title": "Updated Title",
            "status": TaskStatus.IN_PROGRESS.name,
            "assignee": {"assignee_id": self.assignee_id_str, "user_type": "user"},
        }

        result_dto = TaskService.update_task_with_assignee_from_dict(self.task_id_str, validated_data, self.user_id_str)

        mock_repo_get_by_id.assert_called_once_with(self.task_id_str)
        mock_user_get_by_id.assert_called_once_with(self.assignee_id_str)
        mock_repo_update.assert_called_once()
        mock_update_assignment.assert_called_once_with(self.task_id_str, self.assignee_id_str, "user", self.user_id_str)
        mock_prepare_dto.assert_called_once_with(updated_task_model, self.user_id_str)

        self.assertEqual(result_dto, mock_dto_response)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.UserRepository.get_by_id")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_update_task_with_assignee_from_dict_partial_update_only_assignee(
        self, mock_prepare_dto, mock_user_get_by_id, mock_repo_get_by_id
    ):
        mock_repo_get_by_id.return_value = self.default_task_model
        mock_user_get_by_id.return_value = MagicMock()
        mock_dto_response = MagicMock(spec=TaskDTO)
        mock_prepare_dto.return_value = mock_dto_response

        # Only update assignee, no task fields
        validated_data = {
            "assignee": {"assignee_id": self.assignee_id_str, "user_type": "user"},
        }

        result_dto = TaskService.update_task_with_assignee_from_dict(self.task_id_str, validated_data, self.user_id_str)

        # Should not call update since no task fields changed
        mock_prepare_dto.assert_called_once_with(self.default_task_model, self.user_id_str)
        self.assertEqual(result_dto, mock_dto_response)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_update_task_with_assignee_from_dict_partial_update_only_title(
        self, mock_prepare_dto, mock_repo_update, mock_repo_get_by_id
    ):
        mock_repo_get_by_id.return_value = self.default_task_model

        updated_task_model = self.default_task_model.model_copy(deep=True)
        updated_task_model.title = "New Title"
        mock_repo_update.return_value = updated_task_model

        mock_dto_response = MagicMock(spec=TaskDTO)
        mock_prepare_dto.return_value = mock_dto_response

        # Only update title, no assignee
        validated_data = {
            "title": "New Title",
        }

        result_dto = TaskService.update_task_with_assignee_from_dict(self.task_id_str, validated_data, self.user_id_str)

        mock_repo_update.assert_called_once()
        mock_prepare_dto.assert_called_once_with(updated_task_model, self.user_id_str)
        self.assertEqual(result_dto, mock_dto_response)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    def test_update_task_with_assignee_from_dict_task_not_found(self, mock_repo_get_by_id):
        mock_repo_get_by_id.return_value = None

        validated_data = {"title": "Updated Title"}

        with self.assertRaises(TaskNotFoundException) as context:
            TaskService.update_task_with_assignee_from_dict(self.task_id_str, validated_data, self.user_id_str)

        self.assertEqual(str(context.exception), ApiErrors.TASK_NOT_FOUND.format(self.task_id_str))


class TaskServiceDeferTests(TestCase):
    def setUp(self):
        self.task_id = str(ObjectId())
        self.user_id = "system_user"
        self.current_time = datetime.now(timezone.utc)
        self.due_at = self.current_time + timedelta(days=30)
        self.task_model = TaskModel(
            id=self.task_id,
            displayId="TASK-1",
            title="Test Task",
            description="A task for testing deferral.",
            dueAt=self.due_at,
            createdAt=self.current_time - timedelta(days=1),
            createdBy=self.user_id,
        )

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_defer_task_success(self, mock_prepare_dto, mock_repo_update, mock_repo_get_by_id):
        mock_repo_get_by_id.return_value = self.task_model
        deferred_till = self.current_time + timedelta(days=5)

        mock_updated_task = MagicMock()
        mock_repo_update.return_value = mock_updated_task
        mock_dto = MagicMock()
        mock_prepare_dto.return_value = mock_dto

        result_dto = TaskService.defer_task(self.task_id, deferred_till, self.user_id)

        self.assertEqual(result_dto, mock_dto)
        mock_repo_get_by_id.assert_called_once_with(self.task_id)
        mock_repo_update.assert_called_once()
        mock_prepare_dto.assert_called_once_with(mock_updated_task, "system_user")

        update_call_args = mock_repo_update.call_args[0]
        self.assertEqual(update_call_args[0], self.task_id)
        update_payload = update_call_args[1]
        self.assertEqual(update_payload["updatedBy"], self.user_id)
        self.assertIn("deferredDetails", update_payload)
        self.assertEqual(update_payload["deferredDetails"]["deferredTill"], deferred_till)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    def test_defer_task_too_close_to_due_date_raises_exception(self, mock_repo_get_by_id):
        mock_repo_get_by_id.return_value = self.task_model
        deferred_till = self.due_at + timedelta(days=1)

        with self.assertRaises(UnprocessableEntityException):
            TaskService.defer_task(self.task_id, deferred_till, self.user_id)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskService.prepare_task_dto")
    def test_defer_task_without_due_date_success(self, mock_prepare_dto, mock_repo_update, mock_repo_get_by_id):
        self.task_model.dueAt = None
        mock_repo_get_by_id.return_value = self.task_model
        deferred_till = self.current_time + timedelta(days=20)
        mock_repo_update.return_value = MagicMock(spec=TaskModel)

        TaskService.defer_task(self.task_id, deferred_till, self.user_id)

        mock_repo_update.assert_called_once()
        mock_prepare_dto.assert_called_once()
        update_payload = mock_repo_update.call_args[0][1]
        self.assertEqual(update_payload["deferredDetails"]["deferredTill"], deferred_till)
        mock_repo_get_by_id.assert_called_once_with(self.task_id)

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    def test_defer_task_raises_task_not_found(self, mock_repo_get_by_id):
        mock_repo_get_by_id.return_value = None
        deferred_till = self.current_time + timedelta(days=5)

        with self.assertRaises(TaskNotFoundException):
            TaskService.defer_task(self.task_id, deferred_till, self.user_id)

        mock_repo_get_by_id.assert_called_once_with(self.task_id)

    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskRepository.get_by_id")
    def test_defer_task_raises_task_not_found_on_update_failure(self, mock_repo_get_by_id, mock_repo_update):
        mock_repo_get_by_id.return_value = self.task_model
        mock_repo_update.return_value = None
        valid_deferred_till = self.current_time + timedelta(days=5)

        with self.assertRaises(TaskNotFoundException) as context:
            TaskService.defer_task(self.task_id, valid_deferred_till, self.user_id)

        self.assertEqual(str(context.exception), ApiErrors.TASK_NOT_FOUND.format(self.task_id))
        mock_repo_get_by_id.assert_called_once_with(self.task_id)
        mock_repo_update.assert_called_once()

    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskRepository.get_by_id")
    def test_defer_task_on_done_task_raises_conflict(self, mock_repo_get_by_id, mock_repo_update):
        done_task = TaskModel(
            id=self.task_id,
            displayId="#1",
            title="Completed Task",
            status=TaskStatus.DONE.value,
            createdAt=datetime.now(timezone.utc),
            createdBy=str(ObjectId()),
        )
        mock_repo_get_by_id.return_value = done_task
        valid_deferred_till = datetime.now(timezone.utc) + timedelta(days=5)

        with self.assertRaises(TaskStateConflictException) as context:
            TaskService.defer_task(self.task_id, valid_deferred_till, done_task.createdBy)

        self.assertEqual(str(context.exception), ValidationErrors.CANNOT_DEFER_A_DONE_TASK)
        mock_repo_get_by_id.assert_called_once_with(self.task_id)
        mock_repo_update.assert_not_called()

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository.update")
    @patch("todo.services.task_service.TaskRepository._get_assigned_task_ids_for_user")
    def test_defer_task_permission_denied_if_not_creator_or_assignee(
        self, mock_get_assigned, mock_update, mock_get_by_id
    ):
        task_id = self.task_id
        user_id = "not_creator_or_assignee"
        task_model = self.task_model
        task_model.createdBy = "some_other_user"
        mock_get_by_id.return_value = task_model
        mock_get_assigned.return_value = []
        deferred_till = self.current_time + timedelta(days=5)
        with self.assertRaises(PermissionError) as context:
            TaskService.defer_task(task_id, deferred_till, user_id)
        self.assertEqual(str(context.exception), ApiErrors.UNAUTHORIZED_TITLE)
        mock_get_by_id.assert_called_once_with(task_id)
        mock_get_assigned.assert_called_once_with(user_id)
        mock_update.assert_not_called()

    @patch("todo.services.task_service.TaskRepository.get_by_id")
    @patch("todo.services.task_service.TaskRepository._get_assigned_task_ids_for_user")
    @patch("todo.services.task_service.TaskRepository.delete_by_id")
    def test_delete_task_permission_denied_if_not_creator_or_assignee(
        self, mock_delete_by_id, mock_get_assigned, mock_get_by_id
    ):
        task_id = str(ObjectId())
        user_id = "not_creator_or_assignee"
        task_model = MagicMock()
        task_model.createdBy = "some_other_user"
        task_model.id = ObjectId(task_id)
        mock_get_by_id.return_value = task_model
        mock_get_assigned.return_value = []
        mock_delete_by_id.side_effect = PermissionError(ApiErrors.UNAUTHORIZED_TITLE)
        with self.assertRaises(PermissionError) as context:
            TaskService.delete_task(task_id, user_id)
        self.assertEqual(str(context.exception), ApiErrors.UNAUTHORIZED_TITLE)
        mock_get_by_id.assert_not_called()
        mock_get_assigned.assert_not_called()
        mock_delete_by_id.assert_called_once_with(task_id, user_id)
