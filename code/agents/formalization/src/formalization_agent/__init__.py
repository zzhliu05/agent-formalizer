"""Agent 2 input validation and Aristotle preparation utilities."""

from .preparer import PreparationPolicy, PreparationResult, prepare_formalization
from .reader import LoadedTheoremPackage, PackageReadError, load_theorem_package

__all__ = [
    "LoadedTheoremPackage",
    "PackageReadError",
    "PreparationPolicy",
    "PreparationResult",
    "load_theorem_package",
    "prepare_formalization",
]

__version__ = "0.1.0"
