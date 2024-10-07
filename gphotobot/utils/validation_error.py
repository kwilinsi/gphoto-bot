class ValidationError(Exception):
    """
    This exception is thrown when validating user input. It contains a message
    that is intended to be shown to the user.
    """

    def __init__(self, attribute, message, *args):
        """
        Initialize a validation error.

        Args:
            attribute: The name of the attribute that failed validation.
            message: The message to share with the user.
            *args: Args to pass to Exception().
        """

        super().__init__(*args)
        self.message = message
        self.attribute = attribute
