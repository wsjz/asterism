"""Decision gates: the few places where the pipeline waits for a person."""
from .candidates import CANDIDATES_HEADING, Candidate, apply_candidates, preserved_tail, propose_candidates

__all__ = [
    "CANDIDATES_HEADING",
    "Candidate",
    "apply_candidates",
    "preserved_tail",
    "propose_candidates",
]
