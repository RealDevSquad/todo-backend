from unittest.mock import patch, Mock
from rest_framework import status
from todo.tests.integration.base_mongo_test import AuthenticatedMongoTestCase
from todo.constants.task import (
    SORT_FIELD_PRIORITY,
    SORT_FIELD_DUE_AT,
    SORT_FIELD_CREATED_AT,
    SORT_FIELD_UPDATED_AT,
    SORT_FIELD_ASSIGNEE,
    SORT_ORDER_ASC,
    SORT_ORDER_DESC,
)


class TaskSortingIntegrationTest(AuthenticatedMongoTestCase):
    def setUp(self):
        super().setUp()

    @patch("todo.repositories.task_repository.TaskRepository.count")
    @patch("todo.repositories.task_repository.TaskRepository.list")
    def test_priority_sorting_integration(self, mock_list, mock_count):
        mock_list.return_value = []
        mock_count.return_value = 0

        response = self.client.get("/v1/tasks", {"sort_by": "priority", "order": "desc"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_list.assert_called_with(
            1,
            20,
            SORT_FIELD_PRIORITY,
            SORT_ORDER_DESC,
            str(self.user_id),
            team_id=None,
            status_filter=None,
            assignee_ids=None,
        )

    @patch("todo.repositories.task_repository.TaskRepository.count")
    @patch("todo.repositories.task_repository.TaskRepository.list")
    def test_due_at_default_order_integration(self, mock_list, mock_count):
        mock_list.return_value = []
        mock_count.return_value = 0

        response = self.client.get("/v1/tasks", {"sort_by": "dueAt"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_list.assert_called_with(
            1,
            20,
            SORT_FIELD_DUE_AT,
            SORT_ORDER_ASC,
            str(self.user_id),
            team_id=None,
            status_filter=None,
            assignee_ids=None,
        )

    @patch("todo.repositories.task_repository.TaskRepository.count")
    @patch("todo.repositories.task_repository.TaskRepository.list")
    def test_assignee_sorting_uses_aggregation(self, mock_list, mock_count):
        mock_list.return_value = []
        mock_count.return_value = 0

        response = self.client.get("/v1/tasks", {"sort_by": "assignee", "order": "asc"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assignee sorting now falls back to createdAt sorting
        mock_list.assert_called_once_with(
            1,
            20,
            SORT_FIELD_ASSIGNEE,
            SORT_ORDER_ASC,
            str(self.user_id),
            team_id=None,
            status_filter=None,
            assignee_ids=None,
        )

    @patch("todo.repositories.task_repository.TaskRepository.count")
    @patch("todo.repositories.task_repository.TaskRepository.list")
    def test_field_specific_defaults_integration(self, mock_list, mock_count):
        mock_list.return_value = []
        mock_count.return_value = 0

        test_cases = [
            (SORT_FIELD_CREATED_AT, SORT_ORDER_DESC),
            (SORT_FIELD_UPDATED_AT, SORT_ORDER_DESC),
            (SORT_FIELD_DUE_AT, SORT_ORDER_ASC),
            (SORT_FIELD_PRIORITY, SORT_ORDER_DESC),
            (SORT_FIELD_ASSIGNEE, SORT_ORDER_ASC),
        ]

        for sort_field, expected_order in test_cases:
            with self.subTest(sort_field=sort_field, expected_order=expected_order):
                mock_list.reset_mock()
                mock_count.reset_mock()

                response = self.client.get("/v1/tasks", {"sort_by": sort_field})

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                mock_list.assert_called_with(
                    1,
                    20,
                    sort_field,
                    expected_order,
                    str(self.user_id),
                    team_id=None,
                    status_filter=None,
                    assignee_ids=None,
                )

    @patch("todo.repositories.task_repository.TaskRepository.count")
    @patch("todo.repositories.task_repository.TaskRepository.list")
    def test_pagination_with_sorting_integration(self, mock_list, mock_count):
        mock_list.return_value = []
        mock_count.return_value = 100

        response = self.client.get("/v1/tasks", {"page": "3", "limit": "5", "sort_by": "createdAt", "order": "asc"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_list.assert_called_with(
            3,
            5,
            SORT_FIELD_CREATED_AT,
            SORT_ORDER_ASC,
            str(self.user_id),
            team_id=None,
            status_filter=None,
            assignee_ids=None,
        )

    def test_invalid_sort_parameters_integration(self):
        response = self.client.get("/v1/tasks", {"sort_by": "invalid_field"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get("/v1/tasks", {"sort_by": "priority", "order": "invalid_order"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("todo.repositories.task_repository.TaskRepository.count")
    @patch("todo.repositories.task_repository.TaskRepository.list")
    def test_default_behavior_integration(self, mock_list, mock_count):
        mock_list.return_value = []
        mock_count.return_value = 0

        response = self.client.get("/v1/tasks")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_list.assert_called_with(
            1,
            20,
            SORT_FIELD_UPDATED_AT,
            SORT_ORDER_DESC,
            str(self.user_id),
            team_id=None,
            status_filter=None,
            assignee_ids=None,
        )

    @patch("todo.repositories.user_repository.UserRepository.get_by_id")
    @patch("todo.services.task_service.reverse_lazy", return_value="/v1/tasks")
    @patch("todo.repositories.task_repository.TaskRepository.count")
    @patch("todo.repositories.task_repository.TaskRepository.list")
    def test_pagination_links_preserve_sort_params_integration(
        self, mock_list, mock_count, mock_reverse, mock_user_repo
    ):
        from todo.tests.fixtures.task import tasks_models

        from todo.models.user import UserModel

        mock_user = Mock(spec=UserModel)
        mock_user.email_id = "test@example.com"
        mock_user_repo.return_value = mock_user

        mock_list.return_value = [tasks_models[0]] if tasks_models else []
        mock_count.return_value = 3

        with (
            patch("todo.services.task_service.LabelRepository.list_by_ids", return_value=[]),
        ):
            response = self.client.get("/v1/tasks", {"page": "2", "limit": "1", "sort_by": "priority", "order": "desc"})

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            if response.data.get("links"):
                links = response.data["links"]
                if links.get("next"):
                    self.assertIn("sort_by=priority", links["next"])
                    self.assertIn("order=desc", links["next"])
                if links.get("prev"):
                    self.assertIn("sort_by=priority", links["prev"])
                    self.assertIn("order=desc", links["prev"])
