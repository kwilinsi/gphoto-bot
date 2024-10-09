from enum import Enum


class Rotation(Enum):
    DEGREE_0 = 0
    DEGREE_90 = 90
    DEGREE_180 = 180
    DEGREE_270 = 270

    def __str__(self) -> str:
        """
        Get a string with user-friendly language that describes the rotation.

        Returns:
            str: The rotation as a string.
        """

        if self == Rotation.DEGREE_0:
            return "Disabled"
        elif self == Rotation.DEGREE_90:
            return "Clockwise 90 Degrees"
        elif self == Rotation.DEGREE_180:
            return "180 Degrees"
        elif self == Rotation.DEGREE_270:
            return "Counter-clockwise 90 Degrees"
        else:
            raise ValueError(f'Unknown rotation {self.__repr__()}')

    def __repr__(self) -> str:
        return f"Rotation({self.name}={self.value})"
