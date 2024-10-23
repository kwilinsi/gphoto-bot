from typing import Optional


class ValidationError(Exception):
    """
    This exception is thrown when validating user input. It contains a message
    that is intended for the user.
    """

    def __init__(self,
                 *args,
                 attr: Optional[str] = None,
                 msg: Optional[str] = None):
        """
        Initialize a validation error.

        Args:
            *args: Args to pass to Exception().
            attr: The name of the attribute that failed validation.
            msg: The message to share with the user.
        """

        super().__init__(*args)
        self.attr: Optional[str] = attr
        self.msg: Optional[str] = msg
