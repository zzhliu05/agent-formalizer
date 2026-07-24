"""Agent 2 input validation and Aristotle preparation utilities."""

from .generator import (
    GenerationResult,
    generate_proof,
    resume_generation,
    revalidate_generation,
)
from .preparer import PreparationPolicy, PreparationResult, prepare_formalization
from .preparation_reader import LoadedPreparation, load_preparation
from .reader import LoadedTheoremPackage, PackageReadError, load_theorem_package

__all__ = [
    "GenerationResult",
    "LoadedPreparation",
    "LoadedTheoremPackage",
    "PackageReadError",
    "PreparationPolicy",
    "PreparationResult",
    "generate_proof",
    "load_preparation",
    "load_theorem_package",
    "prepare_formalization",
    "resume_generation",
    "revalidate_generation",
]

__version__ = "0.2.0"
