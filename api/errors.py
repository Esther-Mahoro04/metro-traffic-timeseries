"""Errors shared by the MySQL and MongoDB repositories."""


class NotFound(Exception):
    """Raised when an observation id does not exist."""


class Conflict(Exception):
    """Raised when date_time would violate the unique time index."""
