# interpreter/built_in.py
# ruff: noqa: N802

"""
This module contains the main logic of the interpreter.

IPP: You must definitely modify this file. Bend it to your will.

Author: Pavol Kubov <xkubovp00@fit.vut.cz>
"""

from __future__ import annotations

from typing import Any

from interpreter.error_codes import ErrorCode
from interpreter.exceptions import InterpreterError


class SOLObject:
    """
    Base runtime object for the interpreter
    """

    def identicalTo_(self, other: object) -> SOLBoolean:
        """
        Returns true if both operands are the same object.
        """
        return SOLTrue() if self is other else SOLFalse()

    def equalTo_(self, other: object) -> SOLBoolean:
        """
        If both objects expose a 'value' attribute, compare it;
        otherwise fall back to identity comparison (identicalTo_).
        """
        if hasattr(self, "value") and hasattr(other, "value"):
            return SOLTrue() if self.value == other.value else SOLFalse()
        return self.identicalTo_(other)

    def asString(self) -> SOLString:
        """
        Convert object to a string representation.
        """
        return SOLString("")

    def isNumber(self) -> SOLBoolean:
        """
        Return True if object is numeric, default is False.
        """
        return SOLFalse()

    def isString(self) -> SOLBoolean:
        """
        Return True if object is a string, default is False.
        """
        return SOLFalse()

    def isBlock(self) -> SOLBoolean:
        """
        Return True if object is a block, default is False.
        """
        return SOLFalse()

    def isNil(self) -> SOLBoolean:
        """
        Return True if object is nil, default is False.
        """
        return SOLFalse()

    def isBoolean(self) -> SOLBoolean:
        """
        Return True if object is a boolean, default is False.
        """
        return SOLFalse()


class SOLNil(SOLObject):
    """
    Represents the language's nil value.
    """

    _instance: SOLNil | None = None

    def __new__(cls) -> SOLNil:
        """Create or return the singleton instance of SOLNil."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def asString(self) -> SOLString:
        """
        Return string representation of nil.
        """
        return SOLString("nil")

    def isNil(self) -> SOLBoolean:
        """
        Identify this object as nil.
        """
        return SOLTrue()


# Single shared nil instance.
nil: SOLNil = SOLNil()


class SOLBoolean(SOLObject):
    """
    Base class for boolean values (true/false).
    """

    def isBoolean(self) -> SOLBoolean:
        """
        Identify this object as boolean.
        """
        return SOLTrue()


class SOLTrue(SOLBoolean):
    """
    Runtime representation of boolean true.
    """

    def asString(self) -> SOLString:
        """
        Return string representation 'true'.
        """
        return SOLString("true")

    def not_(self) -> SOLBoolean:
        """
        Logical negation of true is false.
        """
        return SOLFalse()

    def and_(self, other: Any) -> object:
        """
        Logical AND.
        """
        return other.value()

    def or_(self, block: Any) -> object:
        """
        Logical OR.
        """
        return self


class SOLFalse(SOLBoolean):
    """
    Runtime representation of boolean false.
    """

    def asString(self) -> SOLString:
        """
        Return string representation 'false'.
        """
        return SOLString("false")

    def not_(self) -> SOLBoolean:
        """
        Logical negation of false is true.
        """
        return SOLTrue()

    def and_(self, block: Any) -> object:
        """
        Logical AND.
        """
        return self

    def or_(self, other: Any) -> object:
        """
        Logical OR.
        """
        return other.value()


class SOLInteger(SOLObject):
    """
    Runtime representation of integer.
    """

    def __init__(self, value: int | str = 0) -> None:
        self.value: int = int(value)

    def isNumber(self) -> SOLBoolean:
        """
        Identify this object as a number.
        """
        return SOLTrue()

    def plus_(self, other: SOLInteger) -> SOLInteger:
        """
        Return new SOLInteger with summed value. (addition)
        """
        return SOLInteger(self.value + other.value)

    def minus_(self, other: SOLInteger) -> SOLInteger:
        """
        Return new SOLInteger with difference. (subtraction)
        """
        return SOLInteger(self.value - other.value)

    def multiplyBy_(self, other: SOLInteger) -> SOLInteger:
        """
        Return new SOLInteger with product. (multiplication)
        """
        return SOLInteger(self.value * other.value)

    def divBy_(self, other: SOLInteger) -> SOLInteger:
        """
        Return new SOLINteger with quotient. (division)
        """
        if other.value == 0:
            raise InterpreterError(ErrorCode.INT_INVALID_ARG, "Division by zero!")
        return SOLInteger(self.value // other.value)

    def greaterThan_(self, other: SOLInteger) -> SOLBoolean:
        """
        Comparison: return True if self > other else False.
        """
        return SOLTrue() if self.value > other.value else SOLFalse()

    def asString(self) -> SOLString:
        """
        String representation of integer value.
        """
        return SOLString(str(self.value))

    def asInteger(self) -> SOLInteger:
        """
        Return self as integer (identity conversion).
        """
        return self

    def equalTo_(self, other: object) -> SOLBoolean:
        """
        Only returns true if other is SOLInteger with same numeric value.
        """
        if not isinstance(other, SOLInteger):
            return SOLFalse()
        return SOLTrue() if self.value == other.value else SOLFalse()


class SOLString(SOLObject):
    """
    Runtime representation of a string.
    """

    def __init__(self, value: str = "") -> None:
        self.value: str = value

    def isString(self) -> SOLBoolean:
        """
        Identify this object as a string.
        """
        return SOLTrue()

    def print_(self) -> SOLString:
        """
        Print the string to standard output without adding a newline.
        """
        print(self.value, end="")
        return self

    def equalTo_(self, other: object) -> SOLBoolean:
        """
        True only if other is SOLString with identical content.
        """
        if not isinstance(other, SOLString):
            return SOLFalse()
        return SOLTrue() if self.value == other.value else SOLFalse()

    def asString(self) -> SOLString:
        """
        Return self as a string.
        """
        return self

    def asInteger(self) -> SOLObject:
        """
        Attempt to parse the string as an integer.
        """
        try:
            return SOLInteger(int(self.value))
        except ValueError:
            return nil

    def concatenateWith_(self, other: SOLObject) -> SOLObject:
        """
        Concatenate with another SOLString. If the other operand is not a string,
        return nil to indicate an invalid operation.
        """
        if not isinstance(other, SOLString):
            return nil
        return SOLString(self.value + other.value)

    def startsWith_endsBefore_(self, a: SOLObject, b: SOLObject) -> SOLObject:
        """
        Return substring from 'a' to 'b - 1'.
        """
        if not isinstance(a, SOLInteger) or not isinstance(b, SOLInteger):
            return nil
        start = a.value
        end = b.value
        if end - start <= 0:
            return SOLString("")
        if start <= 0 or end <= 0:
            return nil
        return SOLString(self.value[start - 1 : end - 1])

    def length(self) -> SOLInteger:
        """
        Return the length of the string as SOLInteger.
        """
        return SOLInteger(len(self.value))
