"""Dynamic versioning for the project."""

from pathlib import Path
import tomllib


def get_version() -> str:
    """Reads the root version.toml file and returns the version.

    Returns:
        (str) The version string.
    """
    with (Path(__file__).parents[1] / "version.toml").open("rb") as f:
        data = tomllib.load(f)

    v = data["version"]
    return f"{v['major']}.{v['minor']}.{v['patch']}"


def write_version_file(version: str, filename: str = "VERSION") -> None:
    """Writes the version string to a file.

    Args:
        version (str): The version string.
        filename (str): The filename to write the version to (relative to project root).
    """
    project_root = Path(__file__).parents[1]
    output_path = project_root / filename
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(version + "\n")


__version__ = get_version()


if __name__ == "__main__":
    write_version_file(get_version())
