# rita

[![CI](https://github.com/SMLoureiro/rita/actions/workflows/ci.yml/badge.svg)](https://github.com/SMLoureiro/rita/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/rita.svg)](https://badge.fury.io/py/rita)
[![codecov](https://codecov.io/gh/SMLoureiro/rita/branch/main/graph/badge.svg)](https://codecov.io/gh/SMLoureiro/rita)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/badge/type--checked-ty-blue?labelColor=orange)](https://github.com/astral-sh/ty)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/SMLoureiro/rita/blob/main/LICENSE)

Render it then argue, a complementary helm toolkit for validation and template creation

## Features

- Fast and modern Python toolchain using Astral's tools (uv, ruff, ty)
- Type-safe with full type annotations
- Command-line interface built with Typer
- Comprehensive documentation with MkDocs — [View Docs](https://SMLoureiro.github.io/rita/)

## Installation

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

### CLI Usage

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

```bash
git clone https://github.com/SMLoureiro/rita.git
cd rita
make install
```

### Running Tests

```bash
make test

# With coverage
make test-cov

# Across all Python versions
make test-matrix
```

### Code Quality

```bash
# Run all checks (lint, format, type-check)
make verify

# Auto-fix lint and format issues
make fix
```

### Prek

```bash
prek install
prek run --all-files
```

### Documentation

```bash
make docs-serve
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
