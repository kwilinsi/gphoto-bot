from abc import ABCMeta

from discord.ext.commands import CogMeta


class CogABCMeta(CogMeta, ABCMeta):
    """
    This is a metaclass to use whenever I need to inherit from both commands.Cog
    and an abstract base class.
    """

    pass
