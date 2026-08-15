from enum import Enum


class UserType(str, Enum):
    USER = "user"
    SUBSCRIBER = "subscriber"