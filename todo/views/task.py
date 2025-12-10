from bson import ObjectId
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.request import Request
from rest_framework.exceptions import ValidationError
from django.conf import settings
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from todo.serializers.get_tasks_serializer import GetTaskQueryParamsSerializer
from todo.serializers.create_task_serializer import CreateTaskSerializer
from todo.serializers.update_task_serializer import UpdateTaskSerializer
from todo.serializers.defer_task_serializer import DeferTaskSerializer
from todo.services.task_service import TaskService
from todo.dto.task_dto import CreateTaskDTO
from todo.dto.responses.create_task_response import CreateTaskResponse
from todo.dto.responses.get_task_by_id_response import GetTaskByIdResponse
from todo.dto.responses.error_response import (
    ApiErrorResponse,
    ApiErrorDetail,
    ApiErrorSource,
)
from todo.constants.messages import ApiErrors
from todo.constants.messages import ValidationErrors
from todo.dto.responses.get_tasks_response import GetTasksResponse
from todo.serializers.create_task_assignment_serializer import AssignTaskToUserSerializer
from todo.services.task_assignment_service import TaskAssignmentService
from todo.dto.responses.create_task_assignment_response import CreateTaskAssignmentResponse
from todo.dto.task_assignment_dto import CreateTaskAssignmentDTO
from todo.exceptions.task_exceptions import TaskNotFoundException
from todo.repositories.team_repository import UserTeamDetailsRepository


class TaskListView(APIView):
    @extend_schema(
        operation_id="get_tasks",
        summary="Get paginated list of tasks",
        description="Retrieve a paginated list of tasks with optional filtering and sorting. Each task now includes an 'in_watchlist' property indicating the watchlist status: true if actively watched, false if in watchlist but inactive, or null if not in watchlist.",
        tags=["tasks"],
        parameters=[
            OpenApiParameter(
                name="page",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Page number for pagination",
            ),
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Number of tasks per page",
            ),
            OpenApiParameter(
                name="teamId",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="If provided, filters tasks assigned to this team.",
                required=False,
            ),
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="If provided, filters tasks by status (e.g., 'DONE', 'IN_PROGRESS', 'TODO', 'BLOCKED', 'DEFERRED').",
                required=False,
            ),
            OpenApiParameter(
                name="assigneeId",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Repeatable parameter that filters tasks assigned to the provided user IDs.",
                required=False,
                many=True,
            ),
        ],
        responses={
            200: OpenApiResponse(response=GetTasksResponse, description="Successful response"),
            400: OpenApiResponse(description="Bad request"),
            403: OpenApiResponse(description="Forbidden"),
            500: OpenApiResponse(description="Internal server error"),
        },
    )
    def get(self, request: Request):
        """
        Retrieve a paginated list of tasks, or if profile=true, only the current user's tasks.
        """
        query = GetTaskQueryParamsSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        if query.validated_data["profile"]:
            status_filter = query.validated_data.get("status", "").upper()
            response = TaskService.get_tasks_for_user(
                user_id=request.user_id,
                page=query.validated_data["page"],
                limit=query.validated_data["limit"],
                status_filter=status_filter,
            )
            return Response(data=response.model_dump(mode="json"), status=status.HTTP_200_OK)

        if query.validated_data["profile"]:
            response = TaskService.get_tasks_for_user(
                user_id=request.user_id,
                page=query.validated_data["page"],
                limit=query.validated_data["limit"],
            )
            return Response(
                data=response.model_dump(mode="json", exclude_none=True),
                status=status.HTTP_200_OK,
            )

        team_id = query.validated_data.get("teamId")
        status_filter = query.validated_data.get("status")
        assignee_ids = query.validated_data.get("assignee_ids")

        if assignee_ids:
            if not team_id:
                raise ValidationError({"teamId": [ValidationErrors.TEAM_ID_REQUIRED_FOR_ASSIGNEE_FILTER]})

            team_members = set(UserTeamDetailsRepository.get_users_by_team_id(team_id))
            invalid_assignees = [assignee_id for assignee_id in assignee_ids if assignee_id not in team_members]

            if invalid_assignees:
                raise ValidationError(
                    {"assigneeId": [f"{ValidationErrors.USER_NOT_TEAM_MEMBER}: {', '.join(invalid_assignees)}"]}
                )

        response = TaskService.get_tasks(
            page=query.validated_data["page"],
            limit=query.validated_data["limit"],
            sort_by=query.validated_data["sort_by"],
            order=query.validated_data.get("order"),
            user_id=request.user_id,
            team_id=team_id,
            status_filter=status_filter,
            assignee_ids=assignee_ids,
        )

        if response.error and response.error.get("code") == "FORBIDDEN":
            return Response(data=response.model_dump(mode="json"), status=status.HTTP_403_FORBIDDEN)

        return Response(data=response.model_dump(mode="json"), status=status.HTTP_200_OK)

    @extend_schema(
        operation_id="create_task",
        summary="Create a new task",
        description="Create a new task with the provided details",
        tags=["tasks"],
        request=CreateTaskSerializer,
        responses={
            201: OpenApiResponse(description="Task created successfully"),
            400: OpenApiResponse(description="Bad request"),
            500: OpenApiResponse(description="Internal server error"),
        },
    )
    def post(self, request: Request):
        """
        Create a new task.

        Args:
            request: HTTP request containing task data

        Returns:
            Response: HTTP response with created task data or error details
        """
        serializer = CreateTaskSerializer(data=request.data)

        if not serializer.is_valid():
            return self._handle_validation_errors(serializer.errors)

        try:
            dto = CreateTaskDTO(**serializer.validated_data, createdBy=request.user_id)
            response: CreateTaskResponse = TaskService.create_task(dto)

            return Response(data=response.model_dump(mode="json"), status=status.HTTP_201_CREATED)

        except ValueError as e:
            if isinstance(e.args[0], ApiErrorResponse):
                error_response = e.args[0]
                return Response(
                    data=error_response.model_dump(mode="json"),
                    status=error_response.statusCode,
                )

            fallback_response = ApiErrorResponse(
                statusCode=500,
                message=ApiErrors.UNEXPECTED_ERROR_OCCURRED,
                errors=[{"detail": (str(e) if settings.DEBUG else ApiErrors.INTERNAL_SERVER_ERROR)}],
            )
            return Response(
                data=fallback_response.model_dump(mode="json"),
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _handle_validation_errors(self, errors):
        formatted_errors = []
        for field, messages in errors.items():
            if isinstance(messages, list):
                for message in messages:
                    formatted_errors.append(
                        ApiErrorDetail(
                            source={ApiErrorSource.PARAMETER: field},
                            title=ApiErrors.VALIDATION_ERROR,
                            detail=str(message),
                        )
                    )
            else:
                formatted_errors.append(
                    ApiErrorDetail(
                        source={ApiErrorSource.PARAMETER: field},
                        title=ApiErrors.VALIDATION_ERROR,
                        detail=str(messages),
                    )
                )

        error_response = ApiErrorResponse(statusCode=400, message=ApiErrors.VALIDATION_ERROR, errors=formatted_errors)

        return Response(
            data=error_response.model_dump(mode="json"),
            status=status.HTTP_400_BAD_REQUEST,
        )


class TaskDetailView(APIView):
    @extend_schema(
        operation_id="get_task_by_id",
        summary="Get task by ID",
        description="Retrieve a single task by its unique identifier",
        tags=["tasks"],
        parameters=[
            OpenApiParameter(
                name="task_id",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description="Unique identifier of the task",
            ),
        ],
        responses={
            200: OpenApiResponse(description="Task retrieved successfully"),
            404: OpenApiResponse(description="Task not found"),
            500: OpenApiResponse(description="Internal server error"),
        },
    )
    def get(self, request: Request, task_id: str):
        """
        Retrieve a single task by ID.
        """
        task_dto = TaskService.get_task_by_id(task_id)
        response_data = GetTaskByIdResponse(data=task_dto)
        return Response(data=response_data.model_dump(mode="json"), status=status.HTTP_200_OK)

    @extend_schema(
        operation_id="delete_task",
        summary="Delete task",
        description="Delete a task by its unique identifier",
        tags=["tasks"],
        parameters=[
            OpenApiParameter(
                name="task_id",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description="Unique identifier of the task to delete",
            ),
        ],
        responses={
            204: OpenApiResponse(description="Task deleted successfully"),
            404: OpenApiResponse(description="Task not found"),
            500: OpenApiResponse(description="Internal server error"),
        },
    )
    def delete(self, request: Request, task_id: str):
        task_id = ObjectId(task_id)
        TaskService.delete_task(task_id, request.user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="update_task",
        summary="Update or defer task",
        description="Partially update a task or defer it based on the action parameter",
        tags=["tasks"],
        parameters=[
            OpenApiParameter(
                name="task_id",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description="Unique identifier of the task",
            ),
            OpenApiParameter(
                name="action",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Action to perform: TODO, IN_PROGRESS, DONE",
            ),
        ],
        request=UpdateTaskSerializer,
        responses={
            200: OpenApiResponse(description="Task updated successfully"),
            400: OpenApiResponse(description="Bad request"),
            404: OpenApiResponse(description="Task not found"),
            500: OpenApiResponse(description="Internal server error"),
        },
    )
    def patch(self, request: Request, task_id: str):
        """
        Partially updates a task by its ID.
        Can also be used to defer a task by using ?action=defer query parameter.
        """
        action = request.query_params.get("action", "update")
        if action == "defer":
            serializer = DeferTaskSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            updated_task_dto = TaskService.defer_task(
                task_id=task_id,
                deferred_till=serializer.validated_data["deferredTill"],
                user_id=request.user_id,
            )
        elif action == "update":
            serializer = UpdateTaskSerializer(data=request.data, partial=True)

            serializer.is_valid(raise_exception=True)

            updated_task_dto = TaskService.update_task(
                task_id=task_id,
                validated_data=serializer.validated_data,
                user_id=request.user_id,
            )
        else:
            raise ValidationError({"action": ValidationErrors.UNSUPPORTED_ACTION.format(action)})

        return Response(data=updated_task_dto.model_dump(mode="json"), status=status.HTTP_200_OK)


class TaskUpdateView(APIView):
    @extend_schema(
        operation_id="update_task_and_assignee",
        summary="Update task and assignee details",
        description="Update both task details and assignee information in a single request. Similar to task creation but for updates.",
        tags=["tasks"],
        parameters=[
            OpenApiParameter(
                name="task_id",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description="Unique identifier of the task to update",
                required=True,
            ),
        ],
        request=UpdateTaskSerializer,
        responses={
            200: OpenApiResponse(description="Task and assignee updated successfully"),
            400: OpenApiResponse(description="Bad request"),
            404: OpenApiResponse(description="Task not found"),
            500: OpenApiResponse(description="Internal server error"),
        },
    )
    def patch(self, request: Request, task_id: str):
        """
        Update both task details and assignee information in a single request.
        Similar to task creation but for updates.
        """
        serializer = UpdateTaskSerializer(data=request.data, partial=True)

        if not serializer.is_valid():
            return self._handle_validation_errors(serializer.errors)

        try:
            # Update the task using the service with validated data
            updated_task_dto = TaskService.update_task_with_assignee_from_dict(
                task_id=task_id, validated_data=serializer.validated_data, user_id=request.user_id
            )

            return Response(data=updated_task_dto.model_dump(mode="json"), status=status.HTTP_200_OK)

        except (ValueError, TaskNotFoundException, PermissionError) as e:
            if isinstance(e, ValueError) and e.args and isinstance(e.args[0], ApiErrorResponse):
                error_response = e.args[0]
                return Response(
                    data=error_response.model_dump(mode="json"),
                    status=error_response.statusCode,
                )

            fallback_response = ApiErrorResponse(
                statusCode=500,
                message=ApiErrors.UNEXPECTED_ERROR_OCCURRED,
                errors=[{"detail": (str(e) if settings.DEBUG else ApiErrors.INTERNAL_SERVER_ERROR)}],
            )
            return Response(
                data=fallback_response.model_dump(mode="json"),
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _handle_validation_errors(self, errors):
        formatted_errors = []
        for field, messages in errors.items():
            if isinstance(messages, list):
                for message in messages:
                    formatted_errors.append(
                        ApiErrorDetail(
                            source={ApiErrorSource.PARAMETER: field},
                            title=ApiErrors.VALIDATION_ERROR,
                            detail=str(message),
                        )
                    )
            else:
                formatted_errors.append(
                    ApiErrorDetail(
                        source={ApiErrorSource.PARAMETER: field},
                        title=ApiErrors.VALIDATION_ERROR,
                        detail=str(messages),
                    )
                )

        error_response = ApiErrorResponse(statusCode=400, message=ApiErrors.VALIDATION_ERROR, errors=formatted_errors)

        return Response(
            data=error_response.model_dump(mode="json"),
            status=status.HTTP_400_BAD_REQUEST,
        )


class AssignTaskToUserView(APIView):
    @extend_schema(
        operation_id="assign_task_to_user",
        summary="Assign task to a user",
        description="Assign a task to a user by user ID. Only authorized users can perform this action.",
        tags=["task-assignments"],
        request=AssignTaskToUserSerializer,
        parameters=[
            OpenApiParameter(
                name="task_id",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                description="Unique identifier of the task",
                required=True,
            ),
        ],
        responses={
            200: OpenApiResponse(response=CreateTaskAssignmentResponse, description="Task assigned successfully"),
            400: OpenApiResponse(
                response=ApiErrorResponse, description="Bad request - validation error or assignee not found"
            ),
            404: OpenApiResponse(response=ApiErrorResponse, description="Task not found"),
            401: OpenApiResponse(response=ApiErrorResponse, description="Unauthorized"),
            500: OpenApiResponse(response=ApiErrorResponse, description="Internal server error"),
        },
    )
    def patch(self, request: Request, task_id: str):
        serializer = AssignTaskToUserSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(data={"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        try:
            dto = CreateTaskAssignmentDTO(
                task_id=task_id, assignee_id=serializer.validated_data["assignee_id"], user_type="user"
            )
            response: CreateTaskAssignmentResponse = TaskAssignmentService.create_task_assignment(dto, request.user_id)
            return Response(data=response.model_dump(mode="json"), status=status.HTTP_200_OK)
        except Exception as e:
            error_response = ApiErrorResponse(
                statusCode=500,
                message=ApiErrors.UNEXPECTED_ERROR_OCCURRED,
                errors=[{"detail": str(e)}],
            )
            return Response(data=error_response.model_dump(mode="json"), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
