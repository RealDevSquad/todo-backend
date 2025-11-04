from typing import Optional

from todo.dto.task_assignment_dto import TaskAssignmentResponseDTO, CreateTaskAssignmentDTO
from todo.dto.responses.create_task_assignment_response import CreateTaskAssignmentResponse
from todo.models.common.pyobjectid import PyObjectId
from todo.models.task_assignment import TaskAssignmentModel
from todo.repositories.task_assignment_repository import TaskAssignmentRepository
from todo.repositories.task_repository import TaskRepository
from todo.repositories.user_repository import UserRepository
from todo.repositories.team_repository import TeamRepository
from todo.exceptions.user_exceptions import UserNotFoundException
from todo.exceptions.task_exceptions import TaskNotFoundException
from todo.dto.task_assignment_dto import TaskAssignmentDTO
from todo.models.audit_log import AuditLogModel
from todo.repositories.audit_log_repository import AuditLogRepository


class TaskAssignmentService:
    @classmethod
    def create_task_assignment(cls, dto: CreateTaskAssignmentDTO, user_id: str) -> CreateTaskAssignmentResponse:
        """
        Create a new task assignment with validation for task, user, and team existence.
        """
        # Validate task exists
        task = TaskRepository.get_by_id(dto.task_id)
        if not task:
            raise TaskNotFoundException(dto.task_id)

        # Validate assignee exists based on user_type
        if dto.user_type == "user":
            assignee = UserRepository.get_by_id(dto.assignee_id)
            if not assignee:
                raise UserNotFoundException(dto.assignee_id)
        elif dto.user_type == "team":
            assignee = TeamRepository.get_by_id(dto.assignee_id)
            if not assignee:
                raise ValueError(f"Team not found: {dto.assignee_id}")
        else:
            raise ValueError("Invalid user_type")

        # Check if task already has an active assignment
        existing_assignment = TaskAssignmentRepository.get_by_task_id(dto.task_id)
        if existing_assignment:
            # If previous assignment was to a team, log unassignment
            if existing_assignment.user_type == "team":
                AuditLogRepository.create(
                    AuditLogModel(
                        task_id=existing_assignment.task_id,
                        team_id=existing_assignment.assignee_id,
                        action="unassigned_from_team",
                        performed_by=PyObjectId(user_id),
                    )
                )
            # Update existing assignment
            updated_assignment = TaskAssignmentRepository.update_assignment(
                dto.task_id, dto.assignee_id, dto.user_type, user_id
            )
            if not updated_assignment:
                raise ValueError("Failed to update task assignment")
            assignment = updated_assignment

        else:
            # Create new assignment
            task_assignment = TaskAssignmentModel(
                task_id=PyObjectId(dto.task_id),
                assignee_id=PyObjectId(dto.assignee_id),
                user_type=dto.user_type,
                created_by=PyObjectId(user_id),
                updated_by=None,
                team_id=PyObjectId(dto.team_id) if dto.team_id else None,
            )
            assignment = TaskAssignmentRepository.create(task_assignment)

            if assignment.user_type == "user" and assignment.team_id:
                AuditLogRepository.create(
                    AuditLogModel(
                        task_id=assignment.task_id,
                        team_id=assignment.team_id,
                        action="assigned_to_member",
                        performed_by=PyObjectId(user_id),
                    )
                )

        # If new assignment is to a team, log assignment
        if assignment.user_type == "team":
            AuditLogRepository.create(
                AuditLogModel(
                    task_id=assignment.task_id,
                    team_id=assignment.assignee_id,
                    action="assigned_to_team",
                    performed_by=PyObjectId(user_id),
                )
            )

        # Also insert into assignee_task_details if this is a team assignment (legacy, can be removed if not needed)
        # if dto.user_type == "team":
        #     TaskAssignmentRepository.create(
        #         TaskAssignmentModel(
        #             assignee_id=PyObjectId(dto.assignee_id),
        #             task_id=PyObjectId(dto.task_id),
        #             user_type="team",
        #             is_active=True,
        #             created_by=PyObjectId(user_id),
        #             updated_by=None,
        #         )
        #     )

        # Prepare response
        response_dto = TaskAssignmentDTO(
            id=str(assignment.id),
            task_id=str(assignment.task_id),
            assignee_id=str(assignment.assignee_id),
            user_type=assignment.user_type,
            executor_id=str(assignment.executor_id) if assignment.executor_id else None,
            is_active=assignment.is_active,
            created_by=str(assignment.created_by),
            updated_by=str(assignment.updated_by) if assignment.updated_by else None,
            created_at=assignment.created_at,
            updated_at=assignment.updated_at,
        )

        return CreateTaskAssignmentResponse(data=response_dto)

    @classmethod
    def get_task_assignment(cls, task_id: str) -> Optional[TaskAssignmentResponseDTO]:
        """
        Get task assignment by task ID.
        """
        assignment = TaskAssignmentRepository.get_by_task_id(task_id)
        if not assignment:
            return None

        # Get assignee name
        if assignment.user_type == "user":
            assignee = UserRepository.get_by_id(str(assignment.assignee_id))
            assignee_name = assignee.name if assignee else "Unknown User"
        elif assignment.user_type == "team":
            assignee = TeamRepository.get_by_id(str(assignment.assignee_id))
            assignee_name = assignee.name if assignee else "Unknown Team"
        else:
            assignee_name = "Unknown"

        return TaskAssignmentResponseDTO(
            id=str(assignment.id),
            task_id=str(assignment.task_id),
            assignee_id=str(assignment.assignee_id),
            user_type=assignment.user_type,
            assignee_name=assignee_name,
            executor_id=str(assignment.executor_id) if assignment.executor_id else None,
            is_active=assignment.is_active,
            created_by=str(assignment.created_by),
            updated_by=str(assignment.updated_by) if assignment.updated_by else None,
            created_at=assignment.created_at,
            updated_at=assignment.updated_at,
        )

    @classmethod
    def delete_task_assignment(cls, task_id: str, user_id: str) -> bool:
        """
        Delete task assignment by task ID.
        """
        return TaskAssignmentRepository.delete_assignment(task_id, user_id)

    @classmethod
    def reassign_tasks_from_user_to_team(cls, user_id: str, team_id: str, performed_by_user_id: str):
        """
        Reassign all tasks of user to team
        """
        return TaskAssignmentRepository.reassign_tasks_from_user_to_team(user_id, team_id, performed_by_user_id)
