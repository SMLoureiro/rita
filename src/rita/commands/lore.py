"""Lore command - the story behind RITA."""

from __future__ import annotations

import rich_click as click

from rita import console as con

RITA_LORE = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                    ✨ RITA - Render It Then Argue ✨                         ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

                                   ❤️

    In the beginning, there was chaos. Helm charts would change, values would
    shift, and nobody knew what Kubernetes manifests would actually be deployed.

    Engineers would argue:

        "Did you change the replica count?"
        "I swear that ConfigMap wasn't there before!"
        "Why is there a new annotation on the Service?"

    The arguments were endless. The diffs were invisible.

    Then came RITA.

    ═══════════════════════════════════════════════════════════════════════════

    R - RENDER    → Transform your Helm charts into actual Kubernetes manifests
    I - IT        → The manifests, the truth, the YAML
    T - THEN      → After rendering, comes the important part...
    A - ARGUE     → Now you can argue about REAL changes, not imagined ones!

    ═══════════════════════════════════════════════════════════════════════════

    With RITA, every pull request shows exactly what will change in your
    cluster. No more guessing. No more surprises. No more:

        "I thought I only changed the image tag..."
        *deploys 47 new resources*

    RITA renders your charts, validates your schemas, tests your deployments,
    and brings peace to your GitOps workflow.

    So next time you're arguing about a Helm chart change, remember:

                        Render It, Then Argue™

                                   💕

    Made with love, for Rita.

╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║   "Behind every successful Kubernetes deployment is someone asking           ║
║    'did you actually render that before you pushed?'"                        ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""


@click.command("lore")
def lore() -> None:
    """Discover the story behind RITA."""
    con.print_lore(RITA_LORE)
