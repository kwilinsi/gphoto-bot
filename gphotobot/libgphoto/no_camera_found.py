class NoCameraFound(Exception):
    """
    This is thrown when a camera was expected but wasn't found, either because
    there are no cameras connected at all or because the specified camera
    wasn't found.
    """
    pass
