from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class RunConfig:
    explicit_files: tuple[Path, ...]
    folder: Path | None
    usernames: tuple[str, ...]
    output_base: Path
    color: Literal["white", "black", "both"] = "both"
    minimum_games: int = 5
    prior_games: float = 8.0
    after: date | None = None
    before: date | None = None
    last_games: int | None = None
    recursive: bool = False
    deduplicate: bool = True
    overwrite: bool = False
    dataset_directory: Path = Path("data")

    def validate(self) -> None:
        if not self.explicit_files and self.folder is None:
            raise ValueError("Supply at least one PGN file or --folder.")
        if not self.usernames or not any(value.strip() for value in self.usernames):
            raise ValueError("Supply at least one non-empty --username.")
        if any(not value.strip() for value in self.usernames):
            raise ValueError("--username values cannot be blank.")
        if self.minimum_games < 1:
            raise ValueError("--minimum-games must be at least 1.")
        if self.prior_games < 0:
            raise ValueError("--prior-games cannot be negative.")
        if self.last_games is not None and self.last_games < 1:
            raise ValueError("--last-games must be at least 1.")
        if self.after and self.before and self.after > self.before:
            raise ValueError("--after cannot be later than --before.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "explicit_files": [str(path.expanduser().resolve()) for path in self.explicit_files],
            "folder": str(self.folder.expanduser().resolve()) if self.folder else None,
            "usernames": list(self.usernames),
            "output_base": str(self.output_base.expanduser().resolve()),
            "color": self.color,
            "minimum_games": self.minimum_games,
            "prior_games": self.prior_games,
            "after": self.after.isoformat() if self.after else None,
            "before": self.before.isoformat() if self.before else None,
            "last_games": self.last_games,
            "recursive": self.recursive,
            "deduplicate": self.deduplicate,
            "overwrite": self.overwrite,
            "dataset_directory": str(self.dataset_directory.expanduser().resolve()),
        }

