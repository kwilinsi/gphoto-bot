from typing import Optional


class ValidationError(Exception):
    """
    This exception is thrown when validating user input. It contains a message
    that is intended for the user.
    """

    def __init__(self,
                 *args,
                 attr: str | None = None,
                 msg: str | None = None):
        """
        Initialize a validation error.

        Args:
            *args: Args to pass to Exception().
            attr: The name of the attribute that failed validation.
            msg: The message to share with the user.
        """

        super().__init__(*args)
        self.attr: str | None = attr
        self.msg: str | None = msg

    def __str__(self) -> str:
        """
        Get a somewhat user-friendly string representation of this error for
        use in log messages. This includes both the attribute and message, if
        they're both present. If either is None, it's omitted.

        Returns:
            A string representation.
        """

        return (
                'ValidationError' +
                (f' on {self.attr}' if self.attr else '') + ': ' +
                (self.msg if self.msg else 'no message given')
        )
