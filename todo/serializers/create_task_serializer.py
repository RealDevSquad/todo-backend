from rest_framework import serializers
from bson import ObjectId
from datetime import datetime
from todo.constants.task import TaskPriority, TaskStatus
from todo.constants.messages import ValidationErrors
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CreateTaskSerializer(serializers.Serializer):
    title = serializers.CharField(required=True, allow_blank=False, help_text="Title of the task")
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, help_text="Description of the task"
    )
    priority = serializers.ChoiceField(
        required=False,
        choices=[priority.name for priority in TaskPriority],
        default=TaskPriority.LOW.name,
        help_text="Priority of the task (LOW, MEDIUM, HIGH)",
    )
    status = serializers.ChoiceField(
        required=False,
        choices=[status.name for status in TaskStatus],
        default=TaskStatus.TODO.name,
        help_text="Status of the task (TODO, IN_PROGRESS, DONE)",
    )
    # Accept assignee_id and user_type at the top level
    assignee_id = serializers.CharField(
        required=False, allow_null=True, help_text="User or team ID to assign the task to"
    )
    user_type = serializers.ChoiceField(
        required=False, choices=["user", "team"], allow_null=True, help_text="Type of assignee: 'user' or 'team'"
    )
    labels = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="List of label IDs",
    )
    timezone = serializers.CharField(
        required=True, allow_null=False, help_text="IANA timezone string like 'Asia/Kolkata'"
    )
    dueAt = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Due date and time in ISO format (UTC)"
    )
    team_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError(ValidationErrors.BLANK_TITLE)
        return value

    def validate_labels(self, value):
        for label_id in value:
            if not ObjectId.is_valid(label_id):
                raise serializers.ValidationError(ValidationErrors.INVALID_OBJECT_ID.format(label_id))
        return value

    def validate(self, data):
        # Compose the 'assignee' dict if assignee_id and user_type are present
        assignee_id = data.pop("assignee_id", None)
        user_type = data.pop("user_type", None)
        team_id = data.pop("team_id", None)
        if assignee_id and user_type:
            if not ObjectId.is_valid(assignee_id):
                raise serializers.ValidationError(
                    {"assignee_id": ValidationErrors.INVALID_OBJECT_ID.format(assignee_id)}
                )
            if user_type not in ["user", "team"]:
                raise serializers.ValidationError({"user_type": "user_type must be either 'user' or 'team'"})
            if team_id and team_id.strip():
                if not ObjectId.is_valid(team_id):
                    raise serializers.ValidationError({"team_id": ValidationErrors.INVALID_OBJECT_ID.format(team_id)})
                data["assignee"] = {"assignee_id": assignee_id, "user_type": user_type, "team_id": team_id}
            else:
                data["assignee"] = {"assignee_id": assignee_id, "user_type": user_type}

        due_at = data.get("dueAt")
        timezone_str = data.get("timezone")

        if due_at:
            if not timezone_str:
                raise serializers.ValidationError({"timezone": ValidationErrors.REQUIRED_TIMEZONE})
            try:
                tz = ZoneInfo(timezone_str)
            except ZoneInfoNotFoundError:
                raise serializers.ValidationError({"timezone": ValidationErrors.INVALID_TIMEZONE})

            now_date = datetime.now(tz).date()
            value_date = due_at.astimezone(tz).date()

            if value_date < now_date:
                raise serializers.ValidationError({"dueAt": ValidationErrors.PAST_DUE_DATE})

        return data
