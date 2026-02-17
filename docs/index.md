# rita

Render it then argue, a complementary helm toolkit for validation and template creation

## Installation

Install using pip:

```bash
pip install rita
```

Or using uv (recommended):

```bash
uv add rita
```

## Quick Start

```python
import rita

print(rita.__version__)
```

### Command Line Interface

rita provides a command-line interface:

```bash
# Show version
rita --version

# Say hello
rita hello World
```

## Development

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) for package management

### Setup

Clone the repository and install dependencies:

```bash
git clone https://github.com/SMLoureiro/rita.git
cd rita
uv sync --group dev
```

### Running Tests

```bash
uv run pytest
```

### Code Quality

```bash
# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check
uv run ty check
```

### Prek Hooks

Install prek hooks:

```bash
prek install
```

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/SMLoureiro/rita/blob/main/LICENSE) file for details.
