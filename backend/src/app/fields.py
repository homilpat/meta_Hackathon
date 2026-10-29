"""Text people write into the record: reasons, comments, notes. One definition for every request model.

The wording of a reason is free (no minimum length, any language); what is refused is a blank or whitespace-only
reason where one is required, so every audited decision carries words a person wrote. Specification content (a
hypothesis statement, an experiment method) keeps its own minimum through `text(min_length)`.
"""

from typing import Annotated

from pydantic import StringConstraints


def text(min_length: int = 1, max_length: int = 2000):
    """Surrounding whitespace is removed before the length is checked."""
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)]


FreeText = text()  # a required reason or comment: any wording, never blank
OptionalText = text(0)  # required only in some branches (a note on EXECUTED); that branch checks it is not empty
