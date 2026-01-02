from unittest.mock import patch
from django.conf import settings
from todo.tests.integration.base_mongo_test import AuthenticatedMongoTestCase
from todo.dto.responses.get_tasks_response import GetTasksResponse


class TaskPaginationIntegrationTest(AuthenticatedMongoTestCase):
    """Integration tests for task pagination settings"""

    def setUp(self):
        super().setUp()

    @patch("todo.services.task_service.TaskService.get_tasks")
    def test_pagination_settings_integration(self, mock_get_tasks):
        """Test that the view and serializer correctly use Django settings for pagination"""
        mock_get_tasks.return_value = GetTasksResponse(tasks=[], links=None)

        default_limit = settings.REST_FRAMEWORK["DEFAULT_PAGINATION_SETTINGS"]["DEFAULT_PAGE_LIMIT"]

        response = self.client.get("/v1/tasks")

        self.assertEqual(response.status_code, 200)
        mock_get_tasks.assert_called_with(
            page=1,
            limit=default_limit,
            sort_by="updatedAt",
            order="desc",
            user_id=str(self.user_id),
            team_id=None,
            status_filter=None,
            assignee_ids=None,
        )

        mock_get_tasks.reset_mock()

        response = self.client.get("/v1/tasks", {"limit": "10"})

        self.assertEqual(response.status_code, 200)
        mock_get_tasks.assert_called_with(
            page=1,
            limit=10,
            sort_by="updatedAt",
            order="desc",
            user_id=str(self.user_id),
            team_id=None,
            status_filter=None,
            assignee_ids=None,
        )

        # Verify API rejects values above max limit
        max_limit = settings.REST_FRAMEWORK["DEFAULT_PAGINATION_SETTINGS"]["MAX_PAGE_LIMIT"]
        response = self.client.get("/v1/tasks", {"limit": str(max_limit + 1)})

        # Should get a 400 error
        self.assertEqual(response.status_code, 400)
        self.assertIn(str(max_limit), str(response.data))
