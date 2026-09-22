"""Base types for classification signals (Classification 2.0).

Placeholder base hierarchy; concrete signals for each canonical class live in
this package (laboratory, appointment, prescription, generic).
"""


class Signal:
    """A single, inspectable reason a document hinted at a document type."""