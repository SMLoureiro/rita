# RITA - Render It Then Argue

RITA provides:
- **Schema generation** - Generate `values.schema.json` files from Pydantic models
- **Manifest rendering** - Render Kubernetes manifests from ArgoCD applications for easy PR diff viewing
- **Configuration management** - YAML-based configuration for paths and settings
- **Authentication** - OCI registry authentication for pulling charts
- **Ephemeral cluster testing** - Test charts with kind clusters

## Installation

The tool is automatically installed when you set up the project:

```bash
uv pip install -e .
```

## Quick Start

```bash
# Initialize configuration (optional, uses defaults if not present)
rita config init

# List ArgoCD applications
rita render list

# Render manifests to see what will be deployed
rita render apply

# Test a chart with dry-run
rita test dry-run --chart <chart-name>
```

## Configuration

The tool uses `.rita.yaml` for configuration. All paths are configurable:

```yaml
# .rita.yaml
auto_discover: true

environments:
  - name: dev
    paths:
      - kubernetes/argocd/applications/dev/templates
    include_patterns:
      - "**/*.yaml"
    exclude_patterns:
      - "**/secrets/**"

  - name: prod
    paths:
      - kubernetes/argocd/applications/prod/templates

charts:
  path: charts                    # Local charts directory
  registry: ghcr.io/SMLoureiro   # OCI registry

render:
  output_path: rendered           # Rendered manifests output
  local_charts_only: true

test:
  kind_cluster_name: rita-test
  timeout_seconds: 300
  cleanup_on_success: true
  cleanup_on_failure: false
```

### Config Commands

```bash
# Initialize a new config file
rita config init

# Show current configuration
rita config show

# Discover ArgoCD applications in any path
rita config discover --path kubernetes/
```

## Commands

### Schema Generation

Generate JSON Schema files for Helm chart values validation:

```bash
# List all charts with schema definitions
rita schema list

# Show schema for a specific chart
rita schema show --chart <chart-name>

# Generate values.schema.json files for all charts
rita schema apply

# Generate for a specific chart only
rita schema apply --chart <chart-name>

# Validate a values file against a schema
rita schema validate --chart <chart-name> kubernetes/<chart-name>/dev-values.yaml
```

### Authentication

Authenticate with OCI registries for pulling charts:

```bash
# Check authentication status
rita auth status

# Login using GitHub CLI credentials (recommended)
rita auth login --use-gh

# Refresh GitHub CLI scopes to include read:packages
rita auth refresh-scopes

# Login with environment variables
export GITHUB_USERNAME=your-username
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxx
rita auth login

# Logout
rita auth logout
```

### Manifest Rendering

Render Kubernetes manifests from ArgoCD applications:

```bash
# List available environments
rita render envs

# List all ArgoCD applications
rita render list

# List only applications using local charts
rita render list --local-only

# List applications for all environments
rita render list --all-envs

# Show rendered manifests for an application (to stdout)
rita render show --app <chart-name>

# Render and save manifests to rendered/ directory
rita render apply --app <chart-name>

# Render all local chart applications
rita render apply

# Render for all environments
rita render apply --all-envs

# Show diff between current and would-be-rendered manifests
rita render diff --app <chart-name>

# Diff all environments
rita render diff --all-envs

# Clean and re-render
rita render apply --clean
```

### Ephemeral Cluster Testing

Test charts with kind clusters:

```bash
# Check if required tools are installed
rita test check

# Create a kind cluster for testing
rita test cluster

# Delete a kind cluster
rita test cluster --delete

# Test a chart with dry-run (no cluster needed)
rita test dry-run --chart <chart-name>

# Test an ArgoCD application configuration
rita test dry-run --app <chart-name> -e dev

# Deploy to kind cluster and verify pods are ready
rita test deploy --chart <chart-name> --create-cluster

# Deploy and clean up after
rita test deploy --app <chart-name> -e dev --cleanup
```

## Rendered Manifests

When you run `rita render apply`, manifests are saved to:

```
rendered/
├── dev/
│   ├── <chart-name>/
│   │   ├── _all.yaml           # Combined manifest
│   │   ├── deployment.yaml     # Grouped by resource kind
│   │   ├── service.yaml
│   │   ├── configmap.yaml
│   │   └── ...
│   └── <chart-name>/
│       └── ...
└── prod/
    └── ...
```

**Benefits:**
- Git diffs show exactly what Kubernetes resources changed
- PR reviews can see the actual manifests, not just values changes
- Easy to spot unintended changes in templating

## Version Handling

When rendering charts, RITA handles version differences:

1. **Versions match**: Uses local chart with `helm dependency build`
2. **Versions differ**: Pulls chart from OCI registry (requires authentication)

```
❯ rita render show -a <chart-name>
  Note: Local version (0.2.4) differs from ArgoCD (0.2.2), pulling from OCI...
```

## Adding New Chart Schemas

1. Create a new package under `rita/charts/<chart_name>/`:

```
rita/charts/my_chart/
├── __init__.py
└── values.py
```

2. Define the schema in `values.py`:

```python
from pydantic import BaseModel, ConfigDict, Field
from rita.charts.utils import ContainerImage, ServiceAccount

class MyChartValues(BaseModel):
    model_config = ConfigDict(extra="allow")
    
    replicaCount: int = Field(default=1, description="Number of replicas")
    image: ContainerImage = Field(
        default_factory=ContainerImage,
        description="Container image configuration"
    )
    # ... more fields
```

3. Export from `__init__.py`:

```python
from rita.charts.my_chart.values import MyChartValues
__all__ = ["MyChartValues"]
```

4. Register in `rita/charts/registry.py`:

```python
from rita.charts.my_chart import MyChartValues

CHART_REGISTRY = {
    ...
    "my-chart": MyChartValues,
}
```

## Common Utility Types

The `rita.charts.utils` module provides reusable types:

- `ContainerImage` - Container image configuration (repository, tag, pullPolicy)
- `ServiceAccount` - Kubernetes ServiceAccount configuration
- `ServiceConfig` - Kubernetes Service configuration
- `IngressConfig` - Ingress configuration
- `AutoscalingConfig` - HPA configuration
- `ProbeConfig` / `HttpProbe` - Liveness/readiness probe configuration
- `EnvFromExternalSecretsConfig` - External secrets integration

## GitHub Action Integration

To show manifest diffs in PRs, create `.github/workflows/helm-diff.yml`:

```yaml
name: Helm Manifest Diff

on:
  pull_request:
    paths:
      - 'charts/**'
      - 'kubernetes/**/values.yaml'
      - 'kubernetes/**/dev-values.yaml'
      - 'kubernetes/**/prod-values.yaml'

jobs:
  diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Install Helm
        uses: azure/setup-helm@v4
        with:
          version: 'v3.14.0'

      - name: Install dependencies
        run: uv pip install -e .

      - name: Login to GitHub Container Registry
        run: |
          echo "${{ secrets.GITHUB_TOKEN }}" | helm registry login ghcr.io -u ${{ github.actor }} --password-stdin

      - name: Generate manifest diff
        id: diff
        run: |
          rita render diff --all-envs > diff_output.txt
          echo "DIFF<<EOF" >> $GITHUB_OUTPUT
          cat diff_output.txt >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT

      - name: Comment on PR
        if: steps.diff.outputs.DIFF != 'No differences found.'
        uses: actions/github-script@v7
        with:
          script: |
            const diff = `${{ steps.diff.outputs.DIFF }}`;
            const body = `## 📦 Helm Manifest Changes
            
            <details>
            <summary>Click to expand manifest diff</summary>
            
            \`\`\`diff
            ${diff}
            \`\`\`
            
            </details>`;
            
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: body
            });
```

## Testing

Run the test suite:

```bash
uv run pytest rita/tests/ -v
```

## Architecture

```
rita/
├── cli.py                    # CLI entry point (click)
├── config.py                 # Configuration management
├── testing.py                # Ephemeral cluster testing
├── charts/
│   ├── registry.py           # Chart name -> Model mapping
│   ├── utils/
│   │   ├── kubernetes.py     # Common K8s types
│   │   └── base.py           # Base chart types
│   ├── patient_app_stack/    # Complex chart with subschemas
│   │   ├── values.py
│   │   └── subschema/
│   ├── patient_backend/
│   ├── patient_multiagent/
│   └── ...
└── tests/
    └── test_schema.py
```

## All Commands Reference

| Command | Description |
|---------|-------------|
| `rita schema list` | List charts with schema definitions |
| `rita schema show` | Display JSON schema |
| `rita schema apply` | Generate values.schema.json |
| `rita schema validate` | Validate values file |
| `rita auth login` | Login to OCI registry |
| `rita auth logout` | Logout from OCI registry |
| `rita auth status` | Check auth status |
| `rita auth refresh-scopes` | Refresh GitHub CLI scopes |
| `rita render envs` | List environments |
| `rita render list` | List ArgoCD applications |
| `rita render show` | Show rendered manifests |
| `rita render apply` | Render and save manifests |
| `rita render diff` | Show manifest differences |
| `rita config init` | Initialize config file |
| `rita config show` | Show current config |
| `rita config discover` | Find ArgoCD applications |
| `rita test check` | Check required tools |
| `rita test cluster` | Create/delete kind cluster |
| `rita test dry-run` | Test with dry-run |
| `rita test deploy` | Deploy and verify |
