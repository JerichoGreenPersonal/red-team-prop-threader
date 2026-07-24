# Project Python Style Guide

## Core Philosophy

- **Clarity over cleverness** - Code is read more than written
- **Explicit over implicit** - No magic, no surprises
- **Consistent over personal** - Team standards matter
- **Typed over dynamic** - Full type hints for safety

## Priority Levels

### CRITICAL (Merge-blocking)

- No prints in library code - use `logging`
- No untyped public APIs
- No bare except clauses - handle specific exceptions or use `contextlib.suppress`
- No mutable default arguments

### IMPORTANT (Review-required)

- All functions must have type hints
- All classes need Google-style docstrings
- Error handling must use specific exceptions
- Use pathlib.Path, not string paths

### PREFERRED (Best practice)

- Functions under 100 lines
- Methods under 50 lines
- Comprehensions max 2 levels deep
- One responsibility per function

## Python Standards

### Version & Setup

- **Target**: Python 3.11+ (managed via `uv`)
- **Line Length**: 160 characters (configured in `ruff.toml`). Applies to code, docstrings, and comments.
- **Linter**: ruff (with flake8-bugbear rules)
- **Formatter**: ruff
- **Type Checker**: ty

### Import Order & Style

```python
# 1. future imports (if needed)
from __future__ import annotations

# 2. standard library
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# 3. third-party
import hiyapyco
import requests
```

### Type Hinting

```python
# PREFERRED: Use modern Union syntax (3.10+)
def process(data: str | None) -> list[int]:
    """Process data and return integers.

    Args:
        data (str | None): The data to process.

    Returns:
        (list[int]) The processed data.
    """
    pass


# use collections.abc for generic types
from collections.abc import Iterable, Mapping


def transform(items: Iterable[str]) -> Mapping[str, int]:
    """Transform items to mapping.

    Args:
        items (Iterable[str]): The items to transform.

    Returns:
        (Mapping[str, int]) The transformed items.
    """
    pass

# avoid typing module when possible
# WRONG: from typing import List, Dict, Optional
# RIGHT: Use built-in types with |
```

### Error Handling

```python
# CORRECT: specific exceptions with context
try:
    data = json.loads(raw_json)
except json.JSONDecodeError as exc:
    # re-raise with context
    raise ValueError(f"Invalid JSON in {file_path}") from exc

# WRONG: bare except or pass
try:
    something()
except:  # NEVER do this
    pass  # NEVER do this

# for intentional suppression (rare)
from contextlib import suppress


with suppress(FileNotFoundError):
    path.unlink()  # ok to ignore if doesn't exist
```

### Logging Standards

**This project uses a shared `core.logger` module** that:

- Provides a `.get(ns: str)` method to retrieve loggers
- Writes to `./logs/<project-name>_YYMMDD.log` files
- Defaults to `INFO` level for console, `DEBUG` level for file
- Initializes on first `.get()` call and reuses logger instances

```python
from core import logger


# create module logger using shared core.logger
_logger = logger.get(__name__)


class DataProcessor:
    """Process data files."""

    def process(self, data_path: Path) -> None:
        """Process a single data file.

        Args:
            data_path (Path): The path to the data file to process.
        """
        _logger.info("Processing data: %s", data_path)

        try:
            # do processing
            _logger.debug("Data processed successfully")

        except Exception as exc:
            _logger.error("Failed to process %s: %s", data_path, exc)
            raise

# NEVER use print() in library code
# WRONG: print(f"Processing {data_path}")
# WRONG: from myproject import _logging
```

**Key logging rules:**

- Always use `from core import logger` then `logger.get(__name__)` instead of `logging.getLogger(__name__)`
- Use `%s` formatting in log messages, not f-strings (more efficient)
- Never use `print()` in library code

### Functions & Methods

```python
def calculate_transforms(
        *,  # Force keyword-only for clarity
        source_matrix: np.ndarray,
        target_space: str = "world",
        apply_scale: bool = False,
) -> np.ndarray:
    """Calculate transformation matrix.

    Args:
        source_matrix (type): Input transformation matrix.
        target_space (type): Target coordinate space.
        apply_scale (type): Whether to apply scale component.

    Returns:
        (type) Transformed matrix in target space.

    Raises:
        (ValueError) If target_space is invalid.
    """
    if target_space not in ("world", "local", "object"):
        raise ValueError(f"Invalid space: {target_space}")

    # implementation here
    return result
```

### Classes & Dataclasses

```python
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)  # Immutable by default
class RecordMetadata:
    """Metadata for data records.

    Attributes:
        record_id (type): Unique record identifier.
        created_at (type): Creation timestamp.
        tags (type): Record categorization tags.
    """
    record_id: str
    created_at: datetime
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """validate metadata after initialization."""
        if not self.record_id:
            raise ValueError("record_id cannot be empty")


class CacheManager:
    """Manage data cache lifecycle.

    This manager handles loading, caching, and
    processing of data records.
    """

    def __init__(self, cache_dir: Path) -> None:
        """Initialize manager with cache directory.

        Args:
            cache_dir (type): Directory for data cache.
        """
        self._cache_dir = cache_dir
        self._cache: dict[str, RecordMetadata] = {}

    def load_record(self, record_id: str) -> RecordMetadata:
        """Load record metadata.

        Args:
            record_id: Unique record identifier.

        Returns:
            Loaded record metadata.

        Raises:
            FileNotFoundError: If record doesn't exist.
        """
        if record_id not in self._cache:
            # load from disk
            pass

        return self._cache[record_id]
```

### Docstring Standards (Google Style)

```python
def complex_operation(
        primary_input: str,
        secondary_data: dict[str, list[int]],
        *,
        validate: bool = True,
        timeout: float | None = None,
) -> tuple[str, int]:
    """Perform complex operation on inputs.

    This function demonstrates proper Google-style docstrings with multiple parameters and return values.
    Line wrap at 110 chars for docstrings.

    Args:
        primary_input (str): Main input string to process.
        secondary_data (dict[str, list[int]]): Mapping of names to integer lists for supplementary processing.
        validate (bool, optional): Whether to validate inputs before processing. Defaults to True.
        timeout (float, optional): Timeout in seconds. None means no timeout. Defaults to None.

    Returns:
        (type[str, int]) A tuple containing:
            - Processed output string
            - Count of operations performed

    Raises:
        (ValueError) If validation fails or inputs are malformed.
        (TimeoutError) If operation exceeds timeout.

    Example:
        >>> result, count = complex_operation(
        ...     "input",
        ...     {"data": [1, 2, 3]},
        ...     timeout=30.0
        ... )
    """
    pass
```

## Function & Method Size

### Critical Rule: No Monolithic Functions

**Functions/methods must NOT exceed 100 lines**. Refactor into helper functions if needed.

```python
# WRONG: 150-line monolithic function
def process_data(data):
    # 30 lines of validation
    # 40 lines of transformation
    # 50 lines of storage
    # 30 lines of cleanup
    pass  # 150 lines total - TOO BIG!


# CORRECT: Refactored with helpers
def process_data(data):
    """Process data with validation and storage."""
    _validate_data(data)
    transformed = _transform_data(data)
    _store_data(transformed)
    return transformed  # ~10 lines - GOOD!


def _validate_data(data): pass  # < 50 lines


def _transform_data(data): pass  # < 50 lines


def _store_data(data): pass  # < 50 lines
```

### Function Size Targets

- **Public functions**: < 100 lines (hard limit)
- **Helper functions**: < 50 lines (preferred)
- **Simple utilities**: < 20 lines (ideal)

## Module Organization

### Avoid Monolithic Files

**Create submodules when a module requires 2+ supporting modules or exceeds ~300-400 lines.**

```text
# WRONG: Flat structure with large files
src/myproject/
├── cache.py      # 800 lines - TOO BIG
├── storage.py    # 600 lines - TOO BIG
└── utils.py      # Unrelated helpers - BAD

# CORRECT: Organized submodules
src/myproject/
├── __init__.py
├── cache/
│   ├── __init__.py
│   ├── manager.py
│   ├── storage.py
│   └── _serializers.py
├── processing/
│   ├── __init__.py
│   ├── processor.py
│   └── validators.py
└── storage/
    ├── __init__.py
    ├── base.py
    └── file.py
```

### Submodule Rules

- Each submodule has `__init__.py` exporting public API
- Internal modules prefixed with `_`
- Max 2 levels deep: `src/package/submodule/module.py`
- Single module < 300 lines
- Related functionality grouped by domain, not type

## Anti-Patterns to Avoid

### String Path Manipulation

```python
# WRONG
import os


path = os.path.join(folder, "subdir", filename)

if os.path.exists(path):
    pass

# CORRECT
from pathlib import Path


path = Path(folder) / "subdir" / filename

if path.exists():
    pass
```

### Untyped Public APIs

```python
# WRONG
def process(data, options=None):
    """Process some data."""
    pass


# CORRECT
def process(
        data: dict[str, Any],
        options: dict[str, bool] | None = None
) -> list[str]:
    """Process data with options.

    Args:
        data (dict[str, Any]): Input data mapping.
        options (dict[str, bool], optional): Processing options. Defaults to None.

    Returns:
        (list[str]) List of processed results.
    """
    options = options or {}
    # implementation
```

### Print Debugging

```python
# WRONG
def calculate(value):
    print(f"Calculating {value}")  # NO!
    result = value * 2
    print(f"Result: {result}")  # NO!
    return result


# CORRECT
from core import logger


_logger = logger.get(__name__)


def calculate(value: float) -> float:
    """Calculate result from value.

    Args:
        value (float): The value to calculate from.

    Returns:
        (float) The calculated result.
    """
    _logger.debug("Calculating value: %s", value)

    result = value * 2

    _logger.debug("Calculated result: %s", result)

    return result
```

### Mutable Defaults

```python
# WRONG - Mutable default
def add_item(item: str, items: list = []):  # BUG!
    items.append(item)
    return items


# CORRECT - None sentinel
def add_item(
        item: str,
        items: list[str] | None = None
) -> list[str]:
    """Add item to list.

    Args:
        item (str): The item to add.
        items (list[str], optional): The list to add the item to. Defaults to None.

    Returns:
        (list[str]) The list with the item added.
    """
    if items is None:
        items = []

    items.append(item)
    return items
```

### Testing Standards

**Use pytest for all testing**

```python
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from myproject.cache import CacheManager, RecordMetadata


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Provide temporary directory for tests."""
    return tmp_path / "test_cache"


@pytest.fixture
def cache_manager(temp_dir: Path) -> CacheManager:
    """Provide CacheManager instance."""
    return CacheManager(temp_dir)


def test_load_existing_record(cache_manager: CacheManager) -> None:
    """Test loading an existing record."""
    # arrange
    record_id = "test_record_001"
    expected = RecordMetadata(
        record_id=record_id,
        created_at=datetime.now(),
        tags=["test"]
    )

    # act
    result = cache_manager.load_record(record_id)

    # assert
    assert result.record_id == record_id


def test_load_missing_record_raises(cache_manager: CacheManager) -> None:
    """Test that missing record raises error."""
    with pytest.raises(FileNotFoundError):
        cache_manager.load_record("nonexistent")


@pytest.mark.parametrize(
    "email,expected",
    [
        ("test@example.com", True),
        ("invalid", False),
    ],
)
def test_validate_email(email: str, expected: bool) -> None:
    """Test email validation."""
    assert validate_email(email) == expected
```

## Build & Validation

All code must pass:

1. **ruff** - No errors or warnings
2. **ruff format** - Properly formatted
3. **ty** - Type checking passes
4. **pytest** - 90%+ coverage on critical paths

```bash
# Run all checks
uv run ruff check .
uv run ruff format --check .
uv run ty check .
uv run pytest

# With coverage
uv run pytest --cov=src --cov-report=html
```
