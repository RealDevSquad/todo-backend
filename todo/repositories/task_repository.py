from datetime import datetime, timezone
from typing import List
from bson import ObjectId
from pymongo import ReturnDocument

from todo.exceptions.task_exceptions import TaskNotFoundException
from todo.models.task import TaskModel
from todo.repositories.common.mongo_repository import MongoRepository
from todo.repositories.task_assignment_repository import TaskAssignmentRepository
from todo.constants.messages import ApiErrors, RepositoryErrors
from todo.constants.task import (
    SORT_FIELD_PRIORITY,
    SORT_FIELD_ASSIGNEE,
    SORT_FIELD_UPDATED_AT,
    SORT_ORDER_DESC,
    TaskStatus,
)
from todo.repositories.team_repository import UserTeamDetailsRepository
from todo.services.enhanced_dual_write_service import EnhancedDualWriteService
from todo.models.postgres import PostgresTask, PostgresDeferredDetails


class TaskRepository(MongoRepository):
    collection_name = TaskModel.collection_name

    @classmethod
    def _get_team_task_ids(cls, team_id: str) -> List[ObjectId]:
        team_tasks = TaskAssignmentRepository.get_collection().find({"team_id": team_id, "is_active": True})
        team_task_ids = [ObjectId(task["task_id"]) for task in team_tasks]
        return list(set(team_task_ids))

    @classmethod
    def _get_task_ids_for_assignees(cls, assignee_ids: List[str], team_id: str | None = None) -> List[ObjectId]:
        """
        Resolve active task IDs for the provided assignee IDs, optionally scoped to a team.
        """
        if not assignee_ids:
            return []

        candidate_values = set()
        for assignee_id in assignee_ids:
            candidate_values.add(assignee_id)
            if ObjectId.is_valid(assignee_id):
                candidate_values.add(ObjectId(assignee_id))

        if not candidate_values:
            return []

        assignment_collection = TaskAssignmentRepository.get_collection()
        assignment_filter: dict = {
            "assignee_id": {"$in": list(candidate_values)},
            "user_type": "user",
            "is_active": True,
        }

        if team_id:
            team_candidates = {team_id}
            if ObjectId.is_valid(team_id):
                team_candidates.add(ObjectId(team_id))
            assignment_filter["team_id"] = {"$in": list(team_candidates)}

        assignments = assignment_collection.find(
            assignment_filter,
            {"task_id": 1},
        )

        task_ids: set[ObjectId] = set()
        for assignment in assignments:
            task_identifier = assignment.get("task_id")
            if isinstance(task_identifier, ObjectId):
                task_ids.add(task_identifier)
            elif isinstance(task_identifier, str) and ObjectId.is_valid(task_identifier):
                task_ids.add(ObjectId(task_identifier))

        return list(task_ids)

    @classmethod
    def _build_status_filter(cls, status_filter: str = None) -> dict:
        now = datetime.now(timezone.utc)

        if status_filter == TaskStatus.DEFERRED.value:
            return {
                "$and": [
                    {"deferredDetails": {"$ne": None}},
                    {"deferredDetails.deferredTill": {"$gt": now}},
                ]
            }

        elif status_filter == TaskStatus.DONE.value:
            return {
                "$or": [
                    {"deferredDetails": None},
                    {"deferredDetails.deferredTill": {"$lt": now}},
                ]
            }

        else:
            return {
                "$and": [
                    {"status": {"$ne": TaskStatus.DONE.value}},
                    {
                        "$or": [
                            {"deferredDetails": None},
                            {"deferredDetails.deferredTill": {"$lt": now}},
                        ]
                    },
                ]
            }

    @classmethod
    def list(
        cls,
        page: int,
        limit: int,
        sort_by: str,
        order: str,
        user_id: str = None,
        team_id: str = None,
        status_filter: str = None,
        assignee_ids: List[str] | None = None,
    ) -> List[TaskModel]:
        tasks_collection = cls.get_collection()

        base_filter = cls._build_status_filter(status_filter)

        filters = [base_filter]

        team_scope_applied = False

        if assignee_ids:
            assignee_task_ids = cls._get_task_ids_for_assignees(assignee_ids, team_id=team_id)
            if not assignee_task_ids:
                return []
            filters.append({"_id": {"$in": assignee_task_ids}})
            if team_id:
                team_scope_applied = True
        elif team_id:
            all_team_task_ids = cls._get_team_task_ids(team_id)
            if not all_team_task_ids:
                return []
            filters.append({"_id": {"$in": all_team_task_ids}})
            team_scope_applied = True

        if user_id and not team_scope_applied:
            assigned_task_ids = cls._get_assigned_task_ids_for_user(user_id)
            user_filters = [{"createdBy": user_id}]
            if assigned_task_ids:
                user_filters.append({"_id": {"$in": assigned_task_ids}})
            filters.append({"$or": user_filters})

        if len(filters) == 1:
            query_filter = filters[0]
        else:
            query_filter = {"$and": filters}

        if sort_by == SORT_FIELD_UPDATED_AT:
            sort_direction = -1 if order == SORT_ORDER_DESC else 1
            pipeline = [
                {"$match": query_filter},
                {"$addFields": {"lastActivity": {"$ifNull": [{"$toDate": "$updatedAt"}, {"$toDate": "$createdAt"}]}}},
                {"$sort": {"lastActivity": sort_direction}},
                {"$skip": (page - 1) * limit},
                {"$limit": limit},
                {"$project": {"lastActivity": 0}},
            ]
            tasks_cursor = tasks_collection.aggregate(pipeline)
            return [TaskModel(**task) for task in tasks_cursor]

        if sort_by == SORT_FIELD_PRIORITY:
            sort_direction = 1 if order == SORT_ORDER_DESC else -1
            sort_criteria = [(sort_by, sort_direction)]
        elif sort_by == SORT_FIELD_ASSIGNEE:
            # Assignee sorting is no longer supported since assignee is in separate collection
            sort_direction = -1 if order == SORT_ORDER_DESC else 1
            sort_criteria = [("createdAt", sort_direction)]
        else:
            sort_direction = -1 if order == SORT_ORDER_DESC else 1
            sort_criteria = [(sort_by, sort_direction)]

        tasks_cursor = tasks_collection.find(query_filter).sort(sort_criteria).skip((page - 1) * limit).limit(limit)
        return [TaskModel(**task) for task in tasks_cursor]

    @classmethod
    def _get_assigned_task_ids_for_user(cls, user_id: str) -> List[ObjectId]:
        """Get task IDs where user is assigned (either directly or as team member)."""
        direct_assignments = TaskAssignmentRepository.get_by_assignee_id(user_id, "user")
        direct_task_ids = [assignment.task_id for assignment in direct_assignments]

        # Get teams where user is a member
        from todo.repositories.team_repository import TeamRepository

        user_teams = UserTeamDetailsRepository.get_by_user_id(user_id)
        team_ids = [str(team.team_id) for team in user_teams]

        # Get tasks assigned to those teams (only if user is POC)
        team_task_ids = []
        if team_ids:
            # Get teams where user is POC
            poc_teams = TeamRepository.get_collection().find(
                {
                    "_id": {"$in": [ObjectId(team_id) for team_id in team_ids]},
                    "is_deleted": False,
                    "poc_id": {"$in": [ObjectId(user_id), user_id]},
                }
            )

            poc_team_ids = [str(team["_id"]) for team in poc_teams]

            # Get team assignments for POC teams
            if poc_team_ids:
                team_assignments = TaskAssignmentRepository.get_collection().find(
                    {"assignee_id": {"$in": poc_team_ids}, "user_type": "team", "is_active": True}
                )
                team_task_ids = [ObjectId(assignment["task_id"]) for assignment in team_assignments]

        return direct_task_ids + team_task_ids

    @classmethod
    def count(
        cls,
        user_id: str = None,
        team_id: str = None,
        status_filter: str = None,
        assignee_ids: List[str] | None = None,
    ) -> int:
        tasks_collection = cls.get_collection()

        base_filter = cls._build_status_filter(status_filter)

        filters = [base_filter]

        team_scope_applied = False

        if assignee_ids:
            assignee_task_ids = cls._get_task_ids_for_assignees(assignee_ids, team_id=team_id)
            if not assignee_task_ids:
                return 0
            filters.append({"_id": {"$in": assignee_task_ids}})
            if team_id:
                team_scope_applied = True
        elif team_id:
            all_team_task_ids = cls._get_team_task_ids(team_id)
            if not all_team_task_ids:
                return 0
            filters.append({"_id": {"$in": all_team_task_ids}})
            team_scope_applied = True

        if user_id and not team_scope_applied:
            assigned_task_ids = cls._get_assigned_task_ids_for_user(user_id)
            user_filters = [{"createdBy": user_id}]
            if assigned_task_ids:
                user_filters.append({"_id": {"$in": assigned_task_ids}})
            filters.append({"$or": user_filters})

        if len(filters) == 1:
            query_filter = filters[0]
        else:
            query_filter = {"$and": filters}

        return tasks_collection.count_documents(query_filter)

    @classmethod
    def get_all(cls) -> List[TaskModel]:
        """
        Get all tasks from the repository

        Returns:
            List[TaskModel]: List of all task models
        """
        tasks_collection = cls.get_collection()
        tasks_cursor = tasks_collection.find()

        return [TaskModel(**task) for task in tasks_cursor]

    @classmethod
    def create(cls, task: TaskModel) -> TaskModel:
        """
        Creates a new task in the repository with a unique displayId, using atomic counter operations.

        Args:
            task (TaskModel): Task to create

        Returns:
            TaskModel: Created task with displayId
        """
        tasks_collection = cls.get_collection()
        client = cls.get_client()

        with client.start_session() as session:
            try:
                with session.start_transaction():
                    # Atomically increment and get the next counter value
                    db = cls.get_database()
                    counter_result = db.counters.find_one_and_update(
                        {"_id": "taskDisplayId"}, {"$inc": {"seq": 1}}, return_document=True, session=session
                    )

                    if not counter_result:
                        db.counters.insert_one({"_id": "taskDisplayId", "seq": 1}, session=session)
                        next_number = 1
                    else:
                        next_number = counter_result["seq"]

                    task.displayId = f"#{next_number}"
                    task.createdAt = datetime.now(timezone.utc)
                    task.updatedAt = None

                    # Ensure createdAt is properly set
                    if not task.createdAt:
                        task.createdAt = datetime.now(timezone.utc)

                    task_dict = task.model_dump(mode="json", by_alias=True, exclude_none=True)
                    insert_result = tasks_collection.insert_one(task_dict, session=session)

                    task.id = insert_result.inserted_id

                    dual_write_service = EnhancedDualWriteService()

                    task_data = {
                        "title": task.title,
                        "description": task.description,
                        "priority": task.priority,
                        "status": task.status,
                        "displayId": task.displayId,
                        "isAcknowledged": task.isAcknowledged,
                        "isDeleted": task.isDeleted,
                        "startedAt": task.startedAt,
                        "dueAt": task.dueAt,
                        "createdAt": task.createdAt or datetime.now(timezone.utc),
                        "updatedAt": task.updatedAt,
                        "createdBy": str(task.createdBy),
                        "updatedBy": str(task.updatedBy) if task.updatedBy else None,
                    }

                    dual_write_success = dual_write_service.create_document(
                        collection_name="tasks", data=task_data, mongo_id=str(task.id)
                    )

                    if not dual_write_success:
                        import logging

                        logger = logging.getLogger(__name__)
                        logger.warning(f"Failed to sync task {task.id} to Postgres")

                    return task

            except Exception as e:
                raise ValueError(RepositoryErrors.TASK_CREATION_FAILED.format(str(e)))

    @classmethod
    def get_by_id(cls, task_id: str) -> TaskModel | None:
        tasks_collection = cls.get_collection()
        task_data = tasks_collection.find_one({"_id": ObjectId(task_id)})
        if task_data:
            return TaskModel(**task_data)
        return None

    @classmethod
    def delete_by_id(cls, task_id: ObjectId, user_id: str) -> TaskModel | None:
        tasks_collection = cls.get_collection()

        task = tasks_collection.find_one({"_id": task_id, "isDeleted": False})
        if not task:
            raise TaskNotFoundException(task_id)

        # Check if user is the creator
        if user_id != task.get("createdBy"):
            # Check if user is assigned to this task
            assigned_task_ids = cls._get_assigned_task_ids_for_user(user_id)
            if task_id not in assigned_task_ids:
                raise PermissionError(ApiErrors.UNAUTHORIZED_TITLE)

        # Deactivate assignee relationship for this task
        TaskAssignmentRepository.deactivate_by_task_id(str(task_id), user_id)

        deleted_task_data = tasks_collection.find_one_and_update(
            {"_id": task_id},
            {
                "$set": {
                    "isDeleted": True,
                    "updatedAt": datetime.now(timezone.utc),
                    "updatedBy": user_id,
                }
            },
            return_document=ReturnDocument.AFTER,
        )

        if deleted_task_data:
            return TaskModel(**deleted_task_data)
        return None

    @classmethod
    def update(cls, task_id: str, update_data: dict) -> TaskModel | None:
        if not isinstance(update_data, dict):
            raise ValueError("update_data must be a dictionary.")

        try:
            obj_id = ObjectId(task_id)
        except Exception:
            return None

        update_data_with_timestamp = {**update_data, "updatedAt": datetime.now(timezone.utc)}
        update_data_with_timestamp.pop("_id", None)
        update_data_with_timestamp.pop("id", None)

        tasks_collection = cls.get_collection()

        updated_task_doc = tasks_collection.find_one_and_update(
            {"_id": obj_id}, {"$set": update_data_with_timestamp}, return_document=ReturnDocument.AFTER
        )

        if updated_task_doc:
            task_model = TaskModel(**updated_task_doc)

            dual_write_service = EnhancedDualWriteService()
            task_data = {
                "title": task_model.title,
                "description": task_model.description,
                "priority": task_model.priority,
                "status": task_model.status,
                "displayId": task_model.displayId,
                "isAcknowledged": task_model.isAcknowledged,
                "isDeleted": task_model.isDeleted,
                "startedAt": task_model.startedAt,
                "dueAt": task_model.dueAt,
                "createdAt": task_model.createdAt,
                "updatedAt": task_model.updatedAt,
                "createdBy": str(task_model.createdBy),
                "updatedBy": str(task_model.updatedBy) if task_model.updatedBy else None,
            }

            dual_write_success = dual_write_service.update_document(
                collection_name="tasks", data=task_data, mongo_id=str(task_model.id)
            )

            if not dual_write_success:
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to sync task update {task_model.id} to Postgres")

            # Handle deferred details if present in update_data
            if "deferredDetails" in update_data:
                cls._handle_deferred_details_sync(task_id, update_data["deferredDetails"])

            return task_model
        return None

    @classmethod
    def get_tasks_for_user(cls, user_id: str, page: int, limit: int, status_filter: str = None) -> List[TaskModel]:
        tasks_collection = cls.get_collection()
        assigned_task_ids = cls._get_assigned_task_ids_for_user(user_id)

        base_filter = cls._build_status_filter(status_filter)

        query = {"$and": [base_filter, {"_id": {"$in": assigned_task_ids}}]}
        tasks_cursor = tasks_collection.find(query).skip((page - 1) * limit).limit(limit)
        return [TaskModel(**task) for task in tasks_cursor]

    @classmethod
    def get_by_ids(cls, task_ids: List[str]) -> List[TaskModel]:
        """
        Get multiple tasks by their IDs in a single database query.
        Returns only the tasks that exist.
        """
        if not task_ids:
            return []
        tasks_collection = cls.get_collection()
        object_ids = [ObjectId(task_id) for task_id in task_ids]
        cursor = tasks_collection.find({"_id": {"$in": object_ids}})
        return [TaskModel(**doc) for doc in cursor]

    @classmethod
    def _handle_deferred_details_sync(cls, task_id: str, deferred_details: dict) -> None:
        """Handle deferred details synchronization to PostgreSQL"""
        try:
            postgres_task = PostgresTask.objects.get(mongo_id=task_id)

            if deferred_details:
                deferred_details_data = {
                    "task": postgres_task,
                    "deferred_at": deferred_details.get("deferredAt"),
                    "deferred_till": deferred_details.get("deferredTill"),
                    "deferred_by": str(deferred_details.get("deferredBy")),
                }

                PostgresDeferredDetails.objects.update_or_create(task=postgres_task, defaults=deferred_details_data)
            else:
                # Remove deferred details if None
                PostgresDeferredDetails.objects.filter(task=postgres_task).delete()

        except PostgresTask.DoesNotExist:
            pass
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to sync deferred details to PostgreSQL for task {task_id}: {str(e)}")
