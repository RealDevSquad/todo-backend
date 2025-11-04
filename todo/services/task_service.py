from typing import List
from dataclasses import dataclass
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from urllib.parse import urlencode
from datetime import datetime, timezone
from todo.dto.deferred_details_dto import DeferredDetailsDTO
from todo.dto.label_dto import LabelDTO
from todo.dto.task_dto import TaskDTO, CreateTaskDTO
from todo.dto.task_assignment_dto import CreateTaskAssignmentDTO
from todo.dto.user_dto import UserDTO
from todo.dto.responses.get_tasks_response import GetTasksResponse
from todo.dto.responses.create_task_response import CreateTaskResponse

from todo.dto.responses.error_response import (
    ApiErrorResponse,
    ApiErrorDetail,
    ApiErrorSource,
)
from todo.dto.responses.paginated_response import LinksData
from todo.exceptions.user_exceptions import UserNotFoundException
from todo.models.task import TaskModel, DeferredDetailsModel
from todo.models.task_assignment import TaskAssignmentModel
from todo.repositories.task_assignment_repository import TaskAssignmentRepository
from todo.dto.task_assignment_dto import TaskAssignmentDTO
from todo.models.common.pyobjectid import PyObjectId
from todo.repositories.task_repository import TaskRepository
from todo.repositories.label_repository import LabelRepository
from todo.repositories.team_repository import TeamRepository
from todo.constants.task import (
    TaskStatus,
    TaskPriority,
)
from todo.constants.messages import ApiErrors, ValidationErrors
from django.conf import settings
from todo.exceptions.task_exceptions import (
    TaskNotFoundException,
    UnprocessableEntityException,
    TaskStateConflictException,
)
from bson.errors import InvalidId as BsonInvalidId

from todo.repositories.user_repository import UserRepository
from todo.repositories.watchlist_repository import WatchlistRepository
import math
from todo.models.audit_log import AuditLogModel
from todo.repositories.audit_log_repository import AuditLogRepository
from todo.services.task_assignment_service import TaskAssignmentService


@dataclass
class PaginationConfig:
    DEFAULT_PAGE: int = 1
    DEFAULT_LIMIT: int = settings.REST_FRAMEWORK["DEFAULT_PAGINATION_SETTINGS"]["DEFAULT_PAGE_LIMIT"]
    MAX_LIMIT: int = settings.REST_FRAMEWORK["DEFAULT_PAGINATION_SETTINGS"]["MAX_PAGE_LIMIT"]


class TaskService:
    DIRECT_ASSIGNMENT_FIELDS = {
        "title",
        "description",
        "dueAt",
        "startedAt",
        "isAcknowledged",
    }

    @classmethod
    def get_tasks(
        cls,
        page: int,
        limit: int,
        sort_by: str,
        order: str,
        user_id: str,
        team_id: str = None,
        status_filter: str = None,
    ) -> GetTasksResponse:
        try:
            cls._validate_pagination_params(page, limit)

            # If team_id is provided, only allow team members to fetch tasks
            if team_id:
                from todo.repositories.team_repository import TeamRepository

                if not TeamRepository.is_user_team_member(team_id, user_id):
                    return GetTasksResponse(
                        tasks=[],
                        links=None,
                        error={
                            "message": "Only team members can view team tasks.",
                            "code": "FORBIDDEN",
                        },
                    )

            tasks = TaskRepository.list(
                page, limit, sort_by, order, user_id, team_id=team_id, status_filter=status_filter
            )
            total_count = TaskRepository.count(user_id, team_id=team_id, status_filter=status_filter)

            if not tasks:
                return GetTasksResponse(tasks=[], links=None)

            task_dtos = [cls.prepare_task_dto(task, user_id) for task in tasks]

            links = cls._build_pagination_links(page, limit, total_count, sort_by, order)

            return GetTasksResponse(tasks=task_dtos, links=links)

        except ValidationError as e:
            return GetTasksResponse(
                tasks=[],
                links=None,
                error={"message": str(e), "code": "VALIDATION_ERROR"},
            )

        except Exception:
            return GetTasksResponse(
                tasks=[],
                links=None,
                error={
                    "message": ApiErrors.UNEXPECTED_ERROR_OCCURRED,
                    "code": "INTERNAL_ERROR",
                },
            )

    @classmethod
    def _validate_pagination_params(cls, page: int, limit: int) -> None:
        if page < 1:
            raise ValidationError("Page must be a positive integer")

        if limit < 1:
            raise ValidationError("Limit must be a positive integer")

        if limit > PaginationConfig.MAX_LIMIT:
            raise ValidationError(f"Maximum limit of {PaginationConfig.MAX_LIMIT} exceeded")

    @classmethod
    def _build_pagination_links(cls, page: int, limit: int, total_count: int, sort_by: str, order: str) -> LinksData:
        """Build pagination links with sort parameters"""

        total_pages = math.ceil(total_count / limit)
        next_link = None
        prev_link = None

        if page < total_pages:
            next_link = cls.build_page_url(page + 1, limit, sort_by, order)

        if page > 1:
            prev_link = cls.build_page_url(page - 1, limit, sort_by, order)

        return LinksData(next=next_link, prev=prev_link)

    @classmethod
    def build_page_url(cls, page: int, limit: int, sort_by: str, order: str) -> str:
        base_url = reverse_lazy("tasks")
        query_params = urlencode({"page": page, "limit": limit, "sort_by": sort_by, "order": order})
        return f"{base_url}?{query_params}"

    @classmethod
    def prepare_task_dto(cls, task_model: TaskModel, user_id: str = None) -> TaskDTO:
        label_dtos = cls._prepare_label_dtos(task_model.labels) if task_model.labels else []
        created_by = cls.prepare_user_dto(task_model.createdBy) if task_model.createdBy else None
        updated_by = cls.prepare_user_dto(task_model.updatedBy) if task_model.updatedBy else None
        deferred_details = (
            cls.prepare_deferred_details_dto(task_model.deferredDetails) if task_model.deferredDetails else None
        )

        assignee_details = TaskAssignmentRepository.get_by_task_id(str(task_model.id))
        assignee_dto = cls._prepare_assignee_dto(assignee_details) if assignee_details else None

        # Check if task is in user's watchlist
        in_watchlist = None
        if user_id:
            watchlist_entry = WatchlistRepository.get_by_user_and_task(user_id, str(task_model.id))
            if watchlist_entry:
                in_watchlist = watchlist_entry.isActive

        task_status = task_model.status

        if task_model.deferredDetails and task_model.deferredDetails.deferredTill > datetime.now(timezone.utc):
            task_status = TaskStatus.DEFERRED.value

        return TaskDTO(
            id=str(task_model.id),
            displayId=task_model.displayId,
            title=task_model.title,
            description=task_model.description,
            assignee=assignee_dto,
            isAcknowledged=task_model.isAcknowledged,
            labels=label_dtos,
            startedAt=task_model.startedAt,
            dueAt=task_model.dueAt,
            status=task_status,
            priority=task_model.priority,
            deferredDetails=deferred_details,
            in_watchlist=in_watchlist,
            createdAt=task_model.createdAt,
            updatedAt=task_model.updatedAt,
            createdBy=created_by,
            updatedBy=updated_by,
        )

    @classmethod
    def _prepare_label_dtos(cls, label_ids: List[str]) -> List[LabelDTO]:
        label_models = LabelRepository.list_by_ids(label_ids)

        return [
            LabelDTO(
                id=str(label_model.id),
                name=label_model.name,
                color=label_model.color,
            )
            for label_model in label_models
        ]

    @classmethod
    def _prepare_assignee_dto(cls, assignee_details: TaskAssignmentModel) -> TaskAssignmentDTO:
        """Prepare assignee DTO from assignee task details."""
        assignee_id = str(assignee_details.assignee_id)

        # Get assignee details based on user_type
        if assignee_details.user_type == "user":
            assignee = UserRepository.get_by_id(assignee_id)
        elif assignee_details.user_type == "team":
            assignee = TeamRepository.get_by_id(assignee_id)
        else:
            return None

        if not assignee:
            return None

        return TaskAssignmentDTO(
            id=str(assignee_details.id),
            task_id=str(assignee_details.task_id),
            assignee_id=assignee_id,
            assignee_name=assignee.name,
            user_type=assignee_details.user_type,
            executor_id=str(assignee_details.executor_id) if assignee_details.executor_id else None,
            team_id=str(assignee_details.team_id) if assignee_details.team_id else None,
            is_active=assignee_details.is_active,
            created_by=str(assignee_details.created_by),
            updated_by=str(assignee_details.updated_by) if assignee_details.updated_by else None,
            created_at=assignee_details.created_at,
            updated_at=assignee_details.updated_at,
        )

    @classmethod
    def prepare_deferred_details_dto(cls, deferred_details_model: DeferredDetailsModel) -> DeferredDetailsDTO | None:
        if not deferred_details_model:
            return None

        deferred_by_user = cls.prepare_user_dto(deferred_details_model.deferredBy)

        return DeferredDetailsDTO(
            deferredAt=deferred_details_model.deferredAt,
            deferredTill=deferred_details_model.deferredTill,
            deferredBy=deferred_by_user,
        )

    @classmethod
    def prepare_user_dto(cls, user_id: str) -> UserDTO:
        user = UserRepository.get_by_id(user_id)
        if user:
            return UserDTO(id=str(user_id), name=user.name)
        raise UserNotFoundException(user_id)

    @classmethod
    def get_task_by_id(cls, task_id: str) -> TaskDTO:
        try:
            task_model = TaskRepository.get_by_id(task_id)
            if not task_model:
                raise TaskNotFoundException(task_id)
            return cls.prepare_task_dto(task_model, user_id=None)
        except BsonInvalidId as exc:
            raise exc

    @classmethod
    def _process_labels_for_update(cls, raw_labels: list | None) -> list[PyObjectId]:
        if raw_labels is None:
            return []

        label_object_ids = [PyObjectId(label_id_str) for label_id_str in raw_labels]
        return label_object_ids

    @classmethod
    def _process_enum_for_update(cls, enum_type: type, value: str | None) -> str | None:
        if value is None:
            return None
        return enum_type[value].value

    @classmethod
    def update_task(cls, task_id: str, validated_data: dict, user_id: str) -> TaskDTO:
        current_task = TaskRepository.get_by_id(task_id)

        if not current_task:
            raise TaskNotFoundException(task_id)

        # Check if user is the creator
        if current_task.createdBy != user_id:
            # Check if user is assigned to this task
            assigned_task_ids = TaskRepository._get_assigned_task_ids_for_user(user_id)
            if current_task.id not in assigned_task_ids:
                raise PermissionError(ApiErrors.UNAUTHORIZED_TITLE)

        # Handle assignee updates if provided
        if validated_data.get("assignee"):
            assignee_info = validated_data["assignee"]
            assignee_id = assignee_info.get("assignee_id")
            user_type = assignee_info.get("user_type")

            if user_type == "user":
                assignee_data = UserRepository.get_by_id(assignee_id)
                if not assignee_data:
                    raise UserNotFoundException(assignee_id)
            elif user_type == "team":
                team_data = TeamRepository.get_by_id(assignee_id)
                if not team_data:
                    raise ValueError(f"Team not found: {assignee_id}")

        # Track status change for audit log
        old_status = getattr(current_task, "status", None)
        new_status = validated_data.get("status")

        update_payload = {}
        enum_fields = {"priority": TaskPriority, "status": TaskStatus}

        for field, value in validated_data.items():
            if field == "labels":
                update_payload[field] = cls._process_labels_for_update(
                    value
                )  # Only convert to ObjectId, do not check existence
            elif field in enum_fields:
                update_payload[field] = cls._process_enum_for_update(enum_fields[field], value)
            elif field in cls.DIRECT_ASSIGNMENT_FIELDS:
                update_payload[field] = value

        # Handle assignee updates separately
        if "assignee" in validated_data:
            assignee_info = validated_data["assignee"]
            TaskAssignmentRepository.update_assignee(
                task_id,
                assignee_info["assignee_id"],
                assignee_info["user_type"],
                user_id,
            )

        if not update_payload:
            return cls.prepare_task_dto(current_task, user_id)

        update_payload["updatedBy"] = user_id
        updated_task = TaskRepository.update(task_id, update_payload)

        # Audit log for status change
        if old_status and new_status and old_status != new_status:
            AuditLogRepository.create(
                AuditLogModel(
                    task_id=current_task.id,
                    action="status_changed",
                    status_from=old_status,
                    status_to=new_status,
                    performed_by=PyObjectId(user_id),
                )
            )

        if not updated_task:
            raise TaskNotFoundException(task_id)

        return cls.prepare_task_dto(updated_task, user_id)

    @classmethod
    def update_task_with_assignee_from_dict(cls, task_id: str, validated_data: dict, user_id: str) -> TaskDTO:
        """
        Update both task details and assignee information in a single operation using validated data dict.
        This allows for true partial updates without requiring all fields.
        """
        current_task = TaskRepository.get_by_id(task_id)

        if not current_task:
            raise TaskNotFoundException(task_id)

        # Check if user is the creator
        if current_task.createdBy != user_id:
            # Check if user is assigned to this task
            assigned_task_ids = TaskRepository._get_assigned_task_ids_for_user(user_id)
            if current_task.id not in assigned_task_ids:
                raise PermissionError(ApiErrors.UNAUTHORIZED_TITLE)

        # Validate assignee if provided
        if validated_data.get("assignee"):
            assignee_info = validated_data["assignee"]
            assignee_id = assignee_info.get("assignee_id")
            user_type = assignee_info.get("user_type")

            if user_type == "user":
                user_data = UserRepository.get_by_id(assignee_id)
                if not user_data:
                    raise UserNotFoundException(assignee_id)
            elif user_type == "team":
                team_data = TeamRepository.get_by_id(assignee_id)
                if not team_data:
                    raise ValueError(f"Team not found: {assignee_id}")

        # Prepare update payload for task fields
        update_payload = {}
        enum_fields = {"priority": TaskPriority, "status": TaskStatus}

        # Process task fields from validated_data
        for field, value in validated_data.items():
            if field == "assignee":
                continue  # Handle assignee separately

            # Skip if the value is the same as current task
            current_value = getattr(current_task, field, None)
            if current_value == value:
                continue

            if field == "labels":
                update_payload[field] = cls._process_labels_for_update(value)
            elif field in enum_fields:
                # For enums, we need to get the name if it's an enum instance, or process as string
                if hasattr(value, "name"):
                    update_payload[field] = value.value
                else:
                    update_payload[field] = cls._process_enum_for_update(enum_fields[field], value)
            elif field in cls.DIRECT_ASSIGNMENT_FIELDS:
                update_payload[field] = value

        # Handle startedAt logic
        if validated_data.get("status") == TaskStatus.IN_PROGRESS and not current_task.startedAt:
            update_payload["startedAt"] = datetime.now(timezone.utc)

        if (
            validated_data.get("status") is not None
            and validated_data.get("status") != TaskStatus.DEFERRED.value
            and current_task.deferredDetails
        ):
            update_payload["deferredDetails"] = None

        if validated_data.get("status") == TaskStatus.DEFERRED.value:
            update_payload["status"] = current_task.status

        # Update task if there are changes
        if update_payload:
            update_payload["updatedBy"] = user_id
            updated_task = TaskRepository.update(task_id, update_payload)
            if not updated_task:
                raise TaskNotFoundException(task_id)
        else:
            updated_task = current_task

        # Handle assignee updates
        if validated_data.get("assignee"):
            TaskAssignmentRepository.update_assignment(
                task_id,
                validated_data["assignee"]["assignee_id"],
                validated_data["assignee"]["user_type"],
                user_id,
            )

        return cls.prepare_task_dto(updated_task, user_id)

    @classmethod
    def update_task_with_assignee(cls, task_id: str, dto: CreateTaskDTO, user_id: str) -> TaskDTO:
        """
        Update both task details and assignee information in a single operation.
        Similar to create_task but for updates.
        """
        current_task = TaskRepository.get_by_id(task_id)

        if not current_task:
            raise TaskNotFoundException(task_id)

        # Check if user is the creator
        if current_task.createdBy != user_id:
            # Check if user is assigned to this task
            assigned_task_ids = TaskRepository._get_assigned_task_ids_for_user(user_id)
            if current_task.id not in assigned_task_ids:
                raise PermissionError(ApiErrors.UNAUTHORIZED_TITLE)

        # Validate assignee if provided
        if dto.assignee:
            assignee_id = dto.assignee.get("assignee_id")
            user_type = dto.assignee.get("user_type")

            if user_type == "user":
                user_data = UserRepository.get_by_id(assignee_id)
                if not user_data:
                    raise UserNotFoundException(assignee_id)
            elif user_type == "team":
                team_data = TeamRepository.get_by_id(assignee_id)
                if not team_data:
                    raise ValueError(f"Team not found: {assignee_id}")

        # Prepare update payload for task fields
        update_payload = {}
        enum_fields = {"priority": TaskPriority, "status": TaskStatus}

        # Process task fields from DTO
        dto_data = dto.model_dump(exclude_none=True, exclude={"assignee", "createdBy"})

        for field, value in dto_data.items():
            # Skip if the value is the same as current task
            current_value = getattr(current_task, field, None)
            if current_value == value:
                continue

            if field == "labels":
                update_payload[field] = cls._process_labels_for_update(value)
            elif field in enum_fields:
                # For enums, we need to get the name if it's an enum instance, or process as string
                if hasattr(value, "name"):
                    update_payload[field] = value.value
                else:
                    update_payload[field] = cls._process_enum_for_update(enum_fields[field], value)
            elif field in cls.DIRECT_ASSIGNMENT_FIELDS:
                update_payload[field] = value

        # Handle startedAt logic
        if dto.status == TaskStatus.IN_PROGRESS and not current_task.startedAt:
            update_payload["startedAt"] = datetime.now(timezone.utc)

        # Update task if there are changes
        if update_payload:
            update_payload["updatedBy"] = user_id
            updated_task = TaskRepository.update(task_id, update_payload)
            if not updated_task:
                raise TaskNotFoundException(task_id)
        else:
            updated_task = current_task

        # Handle assignee updates
        if dto.assignee:
            TaskAssignmentRepository.update_assignment(
                task_id,
                dto.assignee["assignee_id"],
                dto.assignee["user_type"],
                user_id,
            )

        return cls.prepare_task_dto(updated_task, user_id)

    @classmethod
    def defer_task(cls, task_id: str, deferred_till: datetime, user_id: str) -> TaskDTO:
        current_task = TaskRepository.get_by_id(task_id)

        if not current_task:
            raise TaskNotFoundException(task_id)

        # Check if user is the creator
        if current_task.createdBy != user_id:
            # Check if user is assigned to this task
            assigned_task_ids = TaskRepository._get_assigned_task_ids_for_user(user_id)
            if current_task.id not in assigned_task_ids:
                raise PermissionError(ApiErrors.UNAUTHORIZED_TITLE)

        if current_task.status == TaskStatus.DONE:
            raise TaskStateConflictException(ValidationErrors.CANNOT_DEFER_A_DONE_TASK)

        if deferred_till.tzinfo is None:
            deferred_till = deferred_till.replace(tzinfo=timezone.utc)

        if current_task.dueAt:
            due_at = (
                current_task.dueAt.replace(tzinfo=timezone.utc)
                if current_task.dueAt.tzinfo is None
                else current_task.dueAt.astimezone(timezone.utc)
            )

            if deferred_till >= due_at:
                raise UnprocessableEntityException(
                    ValidationErrors.CANNOT_DEFER_TOO_CLOSE_TO_DUE_DATE,
                    source={ApiErrorSource.PARAMETER: "deferredTill"},
                )

        deferred_details = DeferredDetailsModel(
            deferredAt=datetime.now(timezone.utc),
            deferredTill=deferred_till,
            deferredBy=user_id,
        )

        update_payload = {
            "status": TaskStatus.TODO.value,
            "deferredDetails": deferred_details.model_dump(),
            "updatedBy": user_id,
        }

        updated_task = TaskRepository.update(task_id, update_payload)
        if not updated_task:
            raise TaskNotFoundException(task_id)

        return cls.prepare_task_dto(updated_task, user_id)

    @classmethod
    def create_task(cls, dto: CreateTaskDTO) -> CreateTaskResponse:
        now = datetime.now(timezone.utc)
        started_at = now if dto.status == TaskStatus.IN_PROGRESS else None

        # Validate assignee
        if dto.assignee:
            assignee_id = dto.assignee.get("assignee_id")
            user_type = dto.assignee.get("user_type")
            team_id = dto.assignee.get("team_id")

            if user_type == "user":
                user = UserRepository.get_by_id(assignee_id)
                if not user:
                    raise UserNotFoundException(assignee_id)
                if team_id:
                    team = TeamRepository.get_by_id(team_id)
                    if not team:
                        raise ValueError(f"Team not found: {team_id}")
            elif user_type == "team":
                team = TeamRepository.get_by_id(assignee_id)
                if not team:
                    raise ValueError(f"Team not found: {assignee_id}")

        # Removed label existence check

        task = TaskModel(
            id=None,
            title=dto.title,
            description=dto.description,
            priority=dto.priority,
            status=dto.status,
            labels=dto.labels,
            dueAt=dto.dueAt,
            startedAt=started_at,
            createdAt=now,
            isAcknowledged=False,
            isDeleted=False,
            createdBy=dto.createdBy,  # placeholder, will be user_id when auth is in place
        )

        try:
            created_task = TaskRepository.create(task)

            # Create assignee relationship if assignee is provided
            team_id = None
            if dto.assignee:
                if dto.assignee.get("user_type") == "team":
                    team_id = dto.assignee.get("assignee_id")
                elif dto.assignee.get("user_type") == "user" and "team_id" in dto.assignee:
                    team_id = dto.assignee.get("team_id")

                assignee_dto = CreateTaskAssignmentDTO(
                    task_id=str(created_task.id),
                    assignee_id=dto.assignee.get("assignee_id"),
                    user_type=dto.assignee.get("user_type"),
                    team_id=team_id,
                )
                TaskAssignmentService.create_task_assignment(assignee_dto, created_task.createdBy)

            task_dto = cls.prepare_task_dto(created_task, dto.createdBy)
            return CreateTaskResponse(data=task_dto)
        except ValueError as e:
            if isinstance(e.args[0], ApiErrorResponse):
                raise e
            raise ValueError(
                ApiErrorResponse(
                    statusCode=500,
                    message=ApiErrors.REPOSITORY_ERROR,
                    errors=[
                        ApiErrorDetail(
                            source={ApiErrorSource.PARAMETER: "task_repository"},
                            title=ApiErrors.UNEXPECTED_ERROR,
                            detail=(str(e) if settings.DEBUG else ApiErrors.INTERNAL_SERVER_ERROR),
                        )
                    ],
                )
            )
        except Exception as e:
            raise ValueError(
                ApiErrorResponse(
                    statusCode=500,
                    message=ApiErrors.SERVER_ERROR,
                    errors=[
                        ApiErrorDetail(
                            source={ApiErrorSource.PARAMETER: "server"},
                            title=ApiErrors.UNEXPECTED_ERROR,
                            detail=(str(e) if settings.DEBUG else ApiErrors.INTERNAL_SERVER_ERROR),
                        )
                    ],
                )
            )

    @classmethod
    def delete_task(cls, task_id: str, user_id: str) -> None:
        deleted_task_model = TaskRepository.delete_by_id(task_id, user_id)
        if deleted_task_model is None:
            raise TaskNotFoundException(task_id)
        return None

    @classmethod
    def get_tasks_for_user(
        cls,
        user_id: str,
        page: int = PaginationConfig.DEFAULT_PAGE,
        limit: int = PaginationConfig.DEFAULT_LIMIT,
        status_filter: str = None,
    ) -> GetTasksResponse:
        cls._validate_pagination_params(page, limit)
        tasks = TaskRepository.get_tasks_for_user(user_id, page, limit, status_filter=status_filter)
        if not tasks:
            return GetTasksResponse(tasks=[], links=None)

        task_dtos = [cls.prepare_task_dto(task, user_id) for task in tasks]
        return GetTasksResponse(tasks=task_dtos, links=None)
