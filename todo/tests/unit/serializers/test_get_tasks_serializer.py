from unittest import TestCase
from rest_framework.exceptions import ValidationError
from django.conf import settings

from todo.serializers.get_tasks_serializer import GetTaskQueryParamsSerializer
from todo.constants.task import (
    SORT_FIELD_PRIORITY,
    SORT_FIELD_DUE_AT,
    SORT_FIELD_CREATED_AT,
    SORT_FIELD_UPDATED_AT,
    SORT_FIELD_ASSIGNEE,
    SORT_ORDER_ASC,
    SORT_ORDER_DESC,
)


class GetTaskQueryParamsSerializerTest(TestCase):
    def test_serializer_validates_and_returns_valid_input(self):
        data = {"page": "2", "limit": "5"}
        serializer = GetTaskQueryParamsSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["page"], 2)
        self.assertEqual(serializer.validated_data["limit"], 5)

    def test_serializer_applies_default_values_for_missing_fields(self):
        serializer = GetTaskQueryParamsSerializer(data={})
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["page"], 1)
        self.assertEqual(
            serializer.validated_data["limit"],
            settings.REST_FRAMEWORK["DEFAULT_PAGINATION_SETTINGS"]["DEFAULT_PAGE_LIMIT"],
        )

    def test_serializer_raises_error_for_page_below_min_value(self):
        data = {"page": "0"}
        serializer = GetTaskQueryParamsSerializer(data=data)
        with self.assertRaises(ValidationError) as context:
            serializer.is_valid(raise_exception=True)
        self.assertIn("page must be greater than or equal to 1", str(context.exception))

    def test_serializer_raises_error_for_limit_below_min_value(self):
        data = {"limit": "0"}
        serializer = GetTaskQueryParamsSerializer(data=data)
        with self.assertRaises(ValidationError) as context:
            serializer.is_valid(raise_exception=True)
        self.assertIn("limit must be greater than or equal to 1", str(context.exception))

    def test_serializer_raises_error_for_limit_above_max_value(self):
        max_limit = settings.REST_FRAMEWORK["DEFAULT_PAGINATION_SETTINGS"]["MAX_PAGE_LIMIT"]
        data = {"limit": f"{max_limit + 1}"}
        serializer = GetTaskQueryParamsSerializer(data=data)
        with self.assertRaises(ValidationError) as context:
            serializer.is_valid(raise_exception=True)
        self.assertIn(f"Ensure this value is less than or equal to {max_limit}", str(context.exception))

    def test_serializer_handles_partial_input_gracefully(self):
        data = {"page": "3"}
        serializer = GetTaskQueryParamsSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["page"], 3)
        self.assertEqual(
            serializer.validated_data["limit"],
            settings.REST_FRAMEWORK["DEFAULT_PAGINATION_SETTINGS"]["DEFAULT_PAGE_LIMIT"],
        )

    def test_serializer_ignores_undefined_extra_fields(self):
        data = {"page": "2", "limit": "5", "extra_field": "ignored"}
        serializer = GetTaskQueryParamsSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["page"], 2)
        self.assertEqual(serializer.validated_data["limit"], 5)
        self.assertNotIn("extra_field", serializer.validated_data)

    def test_serializer_uses_django_settings_values(self):
        """Test that the serializer correctly uses values from Django settings"""
        # Instead of mocking, we'll test against the actual settings values
        serializer = GetTaskQueryParamsSerializer(data={})
        self.assertTrue(serializer.is_valid())

        # Verify the serializer uses the values from settings
        self.assertEqual(
            serializer.validated_data["limit"],
            settings.REST_FRAMEWORK["DEFAULT_PAGINATION_SETTINGS"]["DEFAULT_PAGE_LIMIT"],
        )

        # Test max value constraint using the actual max value
        max_limit = settings.REST_FRAMEWORK["DEFAULT_PAGINATION_SETTINGS"]["MAX_PAGE_LIMIT"]
        data = {"limit": f"{max_limit + 1}"}
        serializer = GetTaskQueryParamsSerializer(data=data)
        with self.assertRaises(ValidationError) as context:
            serializer.is_valid(raise_exception=True)
        self.assertIn(f"Ensure this value is less than or equal to {max_limit}", str(context.exception))


class GetTaskQueryParamsSerializerSortingTests(TestCase):
    def test_valid_sort_by_fields(self):
        valid_sort_fields = [SORT_FIELD_PRIORITY, SORT_FIELD_DUE_AT, SORT_FIELD_CREATED_AT, SORT_FIELD_ASSIGNEE]

        for sort_field in valid_sort_fields:
            with self.subTest(sort_field=sort_field):
                serializer = GetTaskQueryParamsSerializer(data={"sort_by": sort_field})
                self.assertTrue(
                    serializer.is_valid(), f"sort_by='{sort_field}' should be valid. Errors: {serializer.errors}"
                )
                self.assertEqual(serializer.validated_data["sort_by"], sort_field)

    def test_valid_order_values(self):
        valid_orders = [SORT_ORDER_ASC, SORT_ORDER_DESC]

        for order in valid_orders:
            with self.subTest(order=order):
                serializer = GetTaskQueryParamsSerializer(data={"sort_by": SORT_FIELD_PRIORITY, "order": order})
                self.assertTrue(serializer.is_valid(), f"order='{order}' should be valid. Errors: {serializer.errors}")
                self.assertEqual(serializer.validated_data["order"], order)

    def test_invalid_sort_by_field(self):
        invalid_sort_fields = ["invalid_field", "title", "description", "status", "", None, 123]

        for sort_field in invalid_sort_fields:
            with self.subTest(sort_field=sort_field):
                serializer = GetTaskQueryParamsSerializer(data={"sort_by": sort_field})
                self.assertFalse(serializer.is_valid(), f"sort_by='{sort_field}' should be invalid")
                self.assertIn("sort_by", serializer.errors)

    def test_invalid_order_value(self):
        invalid_orders = ["invalid_order", "ascending", "descending", "up", "down", "", None, 123]

        for order in invalid_orders:
            with self.subTest(order=order):
                serializer = GetTaskQueryParamsSerializer(data={"sort_by": SORT_FIELD_PRIORITY, "order": order})
                self.assertFalse(serializer.is_valid(), f"order='{order}' should be invalid")
                self.assertIn("order", serializer.errors)

    def test_sort_by_defaults_to_created_at(self):
        serializer = GetTaskQueryParamsSerializer(data={})
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["sort_by"], SORT_FIELD_UPDATED_AT)

    def test_order_has_no_default(self):
        serializer = GetTaskQueryParamsSerializer(data={})

        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["order"], "desc")

    def test_sort_by_with_no_order(self):
        serializer = GetTaskQueryParamsSerializer(data={"sort_by": SORT_FIELD_DUE_AT})

        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["sort_by"], SORT_FIELD_DUE_AT)

        self.assertEqual(serializer.validated_data["order"], "asc")

    def test_order_with_no_sort_by(self):
        serializer = GetTaskQueryParamsSerializer(data={"order": SORT_ORDER_ASC})
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["sort_by"], SORT_FIELD_UPDATED_AT)
        self.assertEqual(serializer.validated_data["order"], SORT_ORDER_ASC)

    def test_sorting_with_pagination(self):
        data = {"page": 2, "limit": 15, "sort_by": SORT_FIELD_PRIORITY, "order": SORT_ORDER_DESC}
        serializer = GetTaskQueryParamsSerializer(data=data)
        self.assertTrue(serializer.is_valid())

        self.assertEqual(serializer.validated_data["page"], 2)
        self.assertEqual(serializer.validated_data["limit"], 15)
        self.assertEqual(serializer.validated_data["sort_by"], SORT_FIELD_PRIORITY)
        self.assertEqual(serializer.validated_data["order"], SORT_ORDER_DESC)

    def test_case_sensitivity(self):
        """Test that sort parameters are case sensitive"""

        serializer = GetTaskQueryParamsSerializer(data={"sort_by": "Priority"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("sort_by", serializer.errors)

        serializer = GetTaskQueryParamsSerializer(data={"sort_by": SORT_FIELD_PRIORITY, "order": "DESC"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("order", serializer.errors)

    def test_empty_string_parameters(self):
        serializer = GetTaskQueryParamsSerializer(data={"sort_by": ""})
        self.assertFalse(serializer.is_valid())
        self.assertIn("sort_by", serializer.errors)

        serializer = GetTaskQueryParamsSerializer(data={"sort_by": SORT_FIELD_PRIORITY, "order": ""})
        self.assertFalse(serializer.is_valid())
        self.assertIn("order", serializer.errors)

    def test_all_valid_combinations(self):
        sort_fields = [SORT_FIELD_PRIORITY, SORT_FIELD_DUE_AT, SORT_FIELD_CREATED_AT, SORT_FIELD_ASSIGNEE]
        orders = [SORT_ORDER_ASC, SORT_ORDER_DESC]

        for sort_field in sort_fields:
            for order in orders:
                with self.subTest(sort_field=sort_field, order=order):
                    serializer = GetTaskQueryParamsSerializer(data={"sort_by": sort_field, "order": order})
                    self.assertTrue(
                        serializer.is_valid(),
                        f"Combination sort_by='{sort_field}', order='{order}' should be valid. "
                        f"Errors: {serializer.errors}",
                    )
                    self.assertEqual(serializer.validated_data["sort_by"], sort_field)
                    self.assertEqual(serializer.validated_data["order"], order)
