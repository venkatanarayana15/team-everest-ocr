---
name: python-coder
description: >
  Expert Python coding skill for writing, debugging, refactoring, and optimizing Python code.
  Trigger this skill whenever the user asks to write Python scripts, fix Python bugs, refactor
  existing Python code, build CLI tools, work with Python libraries (pandas, numpy, requests,
  FastAPI, SQLAlchemy, etc.), set up virtual environments, write unit tests with pytest, or
  anything else Python-related. Also use when the user uploads a .py file and asks for help,
  or mentions PEP 8, type hints, decorators, generators, async/await, or Pythonic patterns.
  When in doubt, use this skill — it's better to over-trigger than miss a Python task.
---

# Python Coder

A skill for writing clean, idiomatic, production-grade Python code.

---

## Core Philosophy

- **Pythonic first**: Prefer list comprehensions, generators, context managers, and idiomatic
  patterns over verbose imperative code.
- **Readable over clever**: Follow PEP 8. Code is read far more than it is written.
- **Explicit over implicit**: Clear variable names, type hints, and docstrings — especially
  for functions with non-obvious behavior.
- **Minimal dependencies**: Prefer the standard library unless a third-party package offers
  a meaningful improvement.

---

## Workflow

### 1. Understand the Task

Before writing any code, clarify:
- **Input/Output**: What goes in? What comes out? File? API? stdin/stdout?
- **Scale**: One-off script or reusable module/package?
- **Python version**: Assume 3.10+ unless told otherwise (use `match`, walrus `:=`, etc.)
- **Dependencies**: What's already in the environment? Is there a `requirements.txt` or
  `pyproject.toml`?

If the user uploads a `.py` file, read it fully before suggesting changes.

### 2. Choose the Right Pattern

| Use Case                        | Pattern                                      |
|---------------------------------|----------------------------------------------|
| One-off data processing         | Script with `if __name__ == "__main__"`      |
| Reusable logic                  | Module with functions + type hints           |
| CLI tool                        | `argparse` or `click`                        |
| Web API                         | FastAPI (async) or Flask (sync)              |
| Data analysis                   | pandas + jupyter-friendly functions          |
| Async I/O (HTTP, sockets)       | `asyncio` + `httpx` or `aiohttp`            |
| Background jobs                 | `concurrent.futures` or `celery`            |
| Testing                         | `pytest` with fixtures and parametrize       |

### 3. Write the Code

Follow these standards:

#### Style & Formatting
- Follow **PEP 8** (4-space indents, 79-char lines for code, 72 for docstrings)
- Use **Black**-compatible formatting
- Import order: stdlib → third-party → local (separated by blank lines)

#### Type Hints
Always annotate function signatures:
```python
def process_records(records: list[dict], limit: int = 100) -> list[str]:
    ...
```
Use `from __future__ import annotations` for forward references in older codebases.

#### Docstrings
Use Google-style docstrings for public functions:
```python
def fetch_user(user_id: int) -> dict | None:
    """Fetch a user record by ID.

    Args:
        user_id: The numeric ID of the user to fetch.

    Returns:
        A dict with user data, or None if not found.

    Raises:
        ValueError: If user_id is negative.
    """
```

#### Error Handling
- Use specific exception types — never bare `except:`
- Raise early, handle at the boundary
- Log errors with `logging`, not `print`

```python
import logging

logger = logging.getLogger(__name__)

try:
    result = risky_operation()
except FileNotFoundError as e:
    logger.error("Config file missing: %s", e)
    raise
```

#### Resource Management
Always use context managers for files, DB connections, network sessions:
```python
with open("data.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    rows = list(reader)
```

### 4. Testing

When writing tests, use `pytest`. Always include:
- **Happy path** test
- **Edge case** tests (empty input, None, boundary values)
- **Error case** tests (invalid input, missing file, etc.)

```python
import pytest
from mymodule import parse_date

def test_parse_date_valid():
    assert parse_date("2024-01-15") == date(2024, 1, 15)

def test_parse_date_empty():
    with pytest.raises(ValueError, match="Empty date string"):
        parse_date("")

@pytest.mark.parametrize("raw,expected", [
    ("2024-01-01", date(2024, 1, 1)),
    ("2000-12-31", date(2000, 12, 31)),
])
def test_parse_date_parametrized(raw, expected):
    assert parse_date(raw) == expected
```

### 5. Environment & Packaging

When setting up a project:

```
project/
├── src/
│   └── mypackage/
│       ├── __init__.py
│       └── core.py
├── tests/
│   └── test_core.py
├── pyproject.toml       ← preferred over setup.py
├── requirements.txt     ← for simple scripts
└── README.md
```

Minimal `pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "mypackage"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["requests>=2.31"]
```

Virtual environment setup:
```bash
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
.venv\Scripts\activate         # Windows
pip install -e ".[dev]"
```

---

## Common Patterns & Snippets

### Reading / Writing Files
```python
from pathlib import Path

data = Path("input.txt").read_text(encoding="utf-8")
Path("output.txt").write_text(result, encoding="utf-8")
```

### Working with JSON
```python
import json
from pathlib import Path

config = json.loads(Path("config.json").read_text())
Path("out.json").write_text(json.dumps(result, indent=2))
```

### HTTP Requests
```python
import httpx  # preferred over requests for async support

# Sync
with httpx.Client(timeout=10) as client:
    resp = client.get("https://api.example.com/data")
    resp.raise_for_status()
    return resp.json()

# Async
async def fetch(url: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
```

### Dataclasses
```python
from dataclasses import dataclass, field

@dataclass
class Config:
    host: str = "localhost"
    port: int = 8080
    tags: list[str] = field(default_factory=list)
```

### Generators for Large Data
```python
def read_large_csv(path: str):
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row
```

### CLI with argparse
```python
import argparse

def main():
    parser = argparse.ArgumentParser(description="Process files.")
    parser.add_argument("input", type=str, help="Input file path")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    run(args.input, verbose=args.verbose)

if __name__ == "__main__":
    main()
```

---

## Debugging Checklist

When fixing a bug:
1. Read the **full traceback** — start from the bottom
2. Add `print()` or `logging.debug()` around the suspected line
3. Use `breakpoint()` (built-in pdb) for interactive debugging
4. Check: off-by-one? mutable default argument? wrong variable scope?
5. Check types: `type(x)`, `isinstance(x, ...)`, `repr(x)`

Common gotchas:
- **Mutable default arg**: `def f(items=[])` → use `def f(items=None): items = items or []`
- **Late binding closures** in loops: capture with `lambda x=x: x`
- **`is` vs `==`**: use `==` for value comparison, `is` only for `None`/singletons
- **Encoding**: always specify `encoding="utf-8"` when opening files

---

## Output Format

- Always output **complete, runnable code** — no `...` placeholders unless explicitly
  explaining a pattern
- For multi-file outputs, show each file with its path as a comment at the top:
  ```python
  # src/mypackage/core.py
  ```
- When fixing a bug, briefly explain **what was wrong** and **why the fix works**
- When refactoring, note any **behavior changes** (even intentional ones)

---

## Reference Files

For domain-specific guidance, see:

- `references/async.md` — asyncio patterns, event loops, async context managers
- `references/pandas.md` — DataFrame operations, groupby, merge, memory optimization
- `references/testing.md` — pytest fixtures, mocking, coverage, parametrize advanced usage
- `references/packaging.md` — pyproject.toml deep dive, publishing to PyPI, monorepos

_(Load only the reference relevant to the current task.)_
