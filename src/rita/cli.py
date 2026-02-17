"""RITA CLI - Render It Then Argue.

A CLI tool for Helm chart management with ArgoCD integration.
"""

from __future__ import annotations

import rich_click as click

from rita.commands import auth, chart, config, init, lore, render, schema, test, values

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.USE_MARKDOWN = False
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = True
click.rich_click.STYLE_ERRORS_SUGGESTION = "magenta italic"
click.rich_click.ERRORS_SUGGESTION = (
    "Try running the '--help' flag for more information."
)
click.rich_click.ERRORS_EPILOGUE = "For more information, run: rita lore"
click.rich_click.STYLE_OPTION = "cyan"
click.rich_click.STYLE_ARGUMENT = "green"
click.rich_click.STYLE_COMMAND = "bold yellow"
click.rich_click.STYLE_SWITCH = "cyan"
click.rich_click.HEADER_TEXT = "✨ RITA - Render It Then Argue ✨"
click.rich_click.STYLE_HEADER_TEXT = "bold magenta"
click.rich_click.ALIGN_COMMANDS_PANEL = "left"
click.rich_click.ALIGN_OPTIONS_PANEL = "left"
click.rich_click.MAX_WIDTH = 100

CLI_HELP = """A CLI tool for Helm chart management.

\b
[bold cyan]Features:[/bold cyan]
  [dim]•[/dim] Schema Generation - Generate values.schema.json from Pydantic models
  [dim]•[/dim] Manifest Rendering - Render K8s manifests from ArgoCD applications
  [dim]•[/dim] Chart Testing - Test charts with ephemeral kind clusters

\b
[bold cyan]Quick Start:[/bold cyan]
  [bold yellow]rita schema list[/bold yellow]              List charts with schemas
  [bold yellow]rita schema apply[/bold yellow]             Generate schema files
  [bold yellow]rita render list[/bold yellow]              List ArgoCD applications
  [bold yellow]rita render apply[/bold yellow]             Render manifests
  [bold yellow]rita test dry-run -c CHART[/bold yellow]    Test chart templating

Run [bold magenta]rita lore[/bold magenta] to learn about the story behind RITA!
"""


@click.group(help=CLI_HELP)
def cli() -> None:
    """RITA CLI entry point."""
    pass


cli.add_command(auth)
cli.add_command(chart)
cli.add_command(config)
cli.add_command(init)
cli.add_command(lore)
cli.add_command(render)
cli.add_command(schema)
cli.add_command(test)
cli.add_command(values)


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
