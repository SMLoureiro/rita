from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.table import Table

from rita.console import (
    create_table,
    format_app,
    format_chart,
    format_check,
    format_command,
    format_env,
    format_local_marker,
    format_path,
    format_version,
    print_bullet,
    print_diff,
    print_error,
    print_header,
    print_hint,
    print_info,
    print_key_value,
    print_note,
    print_progress,
    print_subheader,
    print_success,
    print_summary,
    print_warning,
    print_yaml,
)


class TestFormatFunctions:
    def test_format_chart(self):
        result: str = format_chart("my-chart")
        assert "my-chart" in result
        assert len(result) >= len("my-chart")

    def test_format_app(self):
        result: str = format_app("my-app")
        assert "my-app" in result

    def test_format_env(self):
        result: str = format_env("production")
        assert "production" in result

    def test_format_version(self):
        result: str = format_version("1.2.3")
        assert "1.2.3" in result

    def test_format_path(self):
        result: str = format_path("/path/to/file")
        assert "/path/to/file" in result

    def test_format_command(self):
        result: str = format_command("helm install my-chart")
        assert "helm install my-chart" in result

    def test_format_check_exists(self):
        result: str = format_check(True)
        assert len(result) > 0

    def test_format_check_not_exists(self):
        result: str = format_check(False)
        assert len(result) > 0

    def test_format_local_marker_true(self):
        result: str = format_local_marker(True)
        assert len(result) > 0

    def test_format_local_marker_false(self):
        result: str = format_local_marker(False)
        assert isinstance(result, str)


class TestCreateTable:
    def test_create_table_with_title(self):
        table: Table = create_table(title="My Table")
        assert table is not None
        assert table.title == "My Table"

    def test_create_table_without_title(self):
        table: Table = create_table()
        assert table is not None

    def test_create_table_with_header(self):
        table: Table = create_table(show_header=True)
        assert table is not None

    def test_create_table_without_header(self):
        table: Table = create_table(show_header=False)
        assert table is not None


class TestOutputFunctions:
    def test_print_success_no_crash(self):
        print_success("Test message")

    def test_print_error_no_crash(self):
        print_error("Test error")

    def test_print_warning_no_crash(self):
        print_warning("Test warning")

    def test_print_info_no_crash(self):
        print_info("Test info")

    def test_print_header_no_crash(self):
        print_header("Test Header")

    def test_print_subheader_no_crash(self):
        print_subheader("Test Subheader")

    def test_print_key_value_no_crash(self):
        print_key_value("Key", "Value")

    def test_print_bullet_no_crash(self):
        print_bullet("Bullet point")

    def test_print_note_no_crash(self):
        print_note("Note message")

    def test_print_hint_no_crash(self):
        print_hint("Hint message")

    def test_print_yaml_no_crash(self):
        yaml_content = "key: value\nlist:\n  - item1\n  - item2"
        print_yaml(yaml_content, title="YAML Output")

    def test_print_diff_no_crash(self):
        diff_lines = [
            "+ added line",
            "- removed line",
            "  unchanged line",
        ]
        print_diff(diff_lines)

    def test_print_summary_no_crash(self):
        print_summary(success=5, errors=2)

    def test_print_progress_no_crash(self):
        print_progress(current=5, total=10, message="Processing...")
