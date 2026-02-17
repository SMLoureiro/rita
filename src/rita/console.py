"""Rich console output utilities for RITA CLI.

Provides consistent, beautiful CLI output using the Rich library,
similar to modern tools like uv, ruff, and cargo.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Literal, LiteralString

if TYPE_CHECKING:
    from collections.abc import Generator

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

RITA_THEME = Theme(
    {
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "bold red",
        "heading": "bold magenta",
        "highlight": "bold cyan",
        "muted": "dim",
        "chart": "bold blue",
        "app": "bold green",
        "env": "yellow",
        "version": "cyan",
        "path": "dim cyan",
        "command": "bold yellow",
    }
)


console = Console(theme=RITA_THEME)
err_console = Console(theme=RITA_THEME, stderr=True)


def print_success(message: str, prefix: str = "✓") -> None:
    """Print a success message."""
    console.print(f"[success]{prefix}[/success] {message}")


def print_error(message: str, prefix: str = "✗") -> None:
    """Print an error message to stderr."""
    err_console.print(f"[error]{prefix}[/error] {message}")


def print_warning(message: str, prefix: str = "⚠") -> None:
    """Print a warning message."""
    console.print(f"[warning]{prefix}[/warning] {message}")


def print_info(message: str, prefix: str = "•") -> None:
    """Print an info message."""
    console.print(f"[info]{prefix}[/info] {message}")


def print_step(message: str, step: int | None = None) -> None:
    """Print a step in a process."""
    if step is not None:
        console.print(f"[muted]({step})[/muted] {message}")
    else:
        console.print(f"[muted]→[/muted] {message}")


def print_header(title: str) -> None:
    """Print a section header."""
    console.print(f"\n[heading]{title}[/heading]")
    console.print(f"[muted]{'─' * len(title)}[/muted]")


def print_subheader(title: str) -> None:
    """Print a subsection header."""
    console.print(f"\n[bold]{title}[/bold]")


def print_key_value(key: str, value: str, indent: int = 0) -> None:
    """Print a key-value pair."""
    spaces: LiteralString = "  " * indent
    console.print(f"{spaces}[muted]{key}:[/muted] {value}")


def print_bullet(text: str, indent: int = 1) -> None:
    """Print a bullet point."""
    spaces: LiteralString = "  " * indent
    console.print(f"{spaces}[muted]•[/muted] {text}")


def print_tree_item(text: str, is_last: bool = False, indent: int = 0) -> None:
    """Print an item in a tree-like structure."""
    spaces: LiteralString = "  " * indent
    prefix: Literal["└─", "├─"] = "└─" if is_last else "├─"
    console.print(f"{spaces}[muted]{prefix}[/muted] {text}")


def format_chart(name: str) -> str:
    """Format a chart name for display."""
    return f"[chart]{name}[/chart]"


def format_app(name: str) -> str:
    """Format an application name for display."""
    return f"[app]{name}[/app]"


def format_env(name: str) -> str:
    """Format an environment name for display."""
    return f"[env]{name}[/env]"


def format_version(version: str) -> str:
    """Format a version string for display."""
    return f"[version]{version}[/version]"


def format_path(path: str) -> str:
    """Format a path for display."""
    return f"[path]{path}[/path]"


def format_command(cmd: str) -> str:
    """Format a command for display."""
    return f"[command]{cmd}[/command]"


def format_check(exists: bool) -> str:
    """Format a check/cross mark."""
    return "[success]✓[/success]" if exists else "[error]✗[/error]"


def format_local_marker(is_local: bool) -> str:
    """Format a local/remote marker for charts."""
    return "[chart]📦[/chart]" if is_local else "[muted]🌐[/muted]"


def create_table(title: str | None = None, show_header: bool = True) -> Table:
    """Create a styled table."""
    return Table(
        title=title,
        show_header=show_header,
        header_style="bold",
        border_style="muted",
        title_style="heading",
    )


def print_chart_list(charts: list[tuple[str, bool]]) -> None:
    """Print a list of charts with their existence status."""
    table: Table = create_table()
    table.add_column("Status", justify="center", width=6)
    table.add_column("Chart", style="chart")

    for chart_name, exists in charts:
        status: str = format_check(exists)
        table.add_row(status, chart_name)

    console.print(table)


def print_app_list(apps: list[tuple[str, str, str, str, bool, list[str]]]) -> None:
    """Print a list of ArgoCD applications.

    Each app is a tuple of (name, chart_name, version, namespace, is_local, values_files).
    """
    table: Table = create_table()
    table.add_column("", justify="center", width=2)
    table.add_column("Application", style="app")
    table.add_column("Chart", style="chart")
    table.add_column("Version", style="version")
    table.add_column("Namespace")
    table.add_column("Values", style="muted")

    for name, chart_name, version, namespace, is_local, values_files in apps:
        marker: str = format_local_marker(is_local)
        values: str = ", ".join(values_files) if values_files else "-"
        table.add_row(marker, name, chart_name, version, namespace, values)

    console.print(table)


def print_env_list(envs: list[tuple[str, int]]) -> None:
    """Print a list of environments with app counts."""
    table: Table = create_table()
    table.add_column("Environment", style="env")
    table.add_column("Applications", justify="right")

    for env_name, app_count in envs:
        table.add_row(env_name, str(app_count))

    console.print(table)


def print_yaml(content: str, title: str | None = None) -> None:
    """Print YAML content with syntax highlighting."""
    syntax = Syntax(content, "yaml", theme="monokai", line_numbers=False)
    if title:
        console.print(Panel(syntax, title=title, border_style="muted"))
    else:
        console.print(syntax)


def print_json(content: str, title: str | None = None) -> None:
    """Print JSON content with syntax highlighting."""
    syntax = Syntax(content, "json", theme="monokai", line_numbers=False)
    if title:
        console.print(Panel(syntax, title=title, border_style="muted"))
    else:
        console.print(syntax)


def print_diff(diff_lines: list[str]) -> None:
    """Print diff output with appropriate coloring."""
    for line in diff_lines:
        if line.startswith("+") and not line.startswith("+++"):
            console.print(f"[green]{line.rstrip()}[/green]")
        elif line.startswith("-") and not line.startswith("---"):
            console.print(f"[red]{line.rstrip()}[/red]")
        elif line.startswith("@@"):
            console.print(f"[cyan]{line.rstrip()}[/cyan]")
        else:
            console.print(line.rstrip())


def print_panel(content: str, title: str | None = None, style: str = "info") -> None:
    """Print content in a panel/box."""
    console.print(Panel(content, title=title, border_style=style))


def print_banner(title: str, subtitle: str | None = None) -> None:
    """Print a banner/header for the CLI."""
    text = Text()
    text.append(title, style="bold magenta")
    if subtitle:
        text.append(f"\n{subtitle}", style="muted")
    console.print(Panel(text, border_style="magenta"))


def print_progress(current: int, total: int, message: str) -> None:
    """Print a simple progress indicator."""
    console.print(f"[muted][{current}/{total}][/muted] {message}")


def print_summary(success: int, errors: int) -> None:
    """Print a summary of operations."""
    console.print()
    if errors == 0:
        console.print(f"[success]✓ All done![/success] {success} successful")
    else:
        console.print(
            f"[warning]Complete[/warning]: "
            f"[success]{success} successful[/success], "
            f"[error]{errors} errors[/error]"
        )


def print_lore(text: str) -> None:
    """Print the RITA lore with styling."""
    console.print(
        Panel(
            text,
            title="[bold magenta]✨ RITA Lore ✨[/bold magenta]",
            border_style="magenta",
            padding=(1, 2),
        )
    )


def print_command_help(command: str, description: str) -> None:
    """Print help for a command."""
    console.print(f"  {format_command(command):40} {description}")


def print_note(message: str) -> None:
    """Print a note/hint."""
    console.print(f"  [muted]i Note:[/muted] [dim]{message}[/dim]")


def print_hint(message: str) -> None:
    """Print a hint for the user."""
    console.print(f"  [muted]💡 Hint:[/muted] [dim]{message}[/dim]")


# ============================================================================
# Progress & Spinner Utilities
# ============================================================================


@contextmanager
def spinner(
    message: str, done_message: str | None = None
) -> Generator[None]:
    """Context manager that shows a spinner during long-running operations.

    Usage:
        with spinner("Rendering charts..."):
            do_long_task()

        # With custom done message
        with spinner("Rendering...", done_message="Rendered 5 charts"):
            do_long_task()
    """
    spin = Spinner("dots", text=f" {message}", style="cyan")
    with Live(spin, console=console, refresh_per_second=10, transient=True):
        yield

    if done_message:
        print_success(done_message)


@contextmanager
def status(message: str) -> Generator[StatusUpdater]:
    """Context manager that shows a spinner with updatable status text.

    Usage:
        with status("Rendering charts...") as s:
            for i, chart in enumerate(charts):
                s.update(f"Rendering {chart.name}... ({i+1}/{len(charts)})")
                render_chart(chart)
    """
    updater = StatusUpdater(message)
    with Live(updater.spinner, console=console, refresh_per_second=10, transient=True):
        yield updater


class StatusUpdater:
    """Helper class for updating spinner status text."""

    def __init__(self, initial_message: str):
        self.message = initial_message
        self.spinner = Spinner("dots", text=f" {initial_message}", style="cyan")

    def update(self, message: str) -> None:
        """Update the spinner status text."""
        self.message = message
        self.spinner.update(text=f" {message}")


def create_progress(
    description: str = "Processing...", show_time: bool = True  # noqa: ARG001
) -> Progress:
    """Create a progress bar with spinner for tracked operations.

    Usage:
        with create_progress("Rendering") as progress:
            task = progress.add_task("Rendering charts...", total=len(apps))
            for app in apps:
                render_app(app)
                progress.advance(task)
    """
    columns = [
        SpinnerColumn("dots"),
        TextColumn("[progress.description]{task.description}"),
    ]
    if show_time:
        columns.append(TimeElapsedColumn())

    return Progress(*columns, console=console, transient=True)
