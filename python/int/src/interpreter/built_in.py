# ruff: noqa: N802

"""
This module contains the main logic of the interpreter.

IPP: You must definitely modify this file. Bend it to your will.

Author: Pavol Kubov <xkubovp00@fit.vut.cz>
"""

from interpreter.error_codes import ErrorCode
from interpreter.exceptions import InterpreterError

# ======================
# BASE OBJECT
# ======================


class SOLObject:
    """
    Base runtime object for the interpreter
    """

    def identicalTo_(self, other):
        """
        Returns true if both operands are the same object.
        """
        return SOLTrue() if self is other else SOLFalse()

    def equalTo_(self, other):
        """
        If both objects expose a 'value' attribute, compare it;
        otherwise fall back to identity comparison (identicalTo_).
        """
        if hasattr(self, "value") and hasattr(other, "value"):
            return SOLTrue() if self.value == other.value else SOLFalse()
        return self.identicalTo_(other)

    def asString(self):
        """
        Convert object to a string representation.
        """
        return SOLString("")

    def isNumber(self):
        """
        Return True if object is numeric, default is False.
        """
        return SOLFalse()

    def isString(self):
        """
        Return True if object is a string, default is False.
        """
        return SOLFalse()

    def isBlock(self):
        """
        Return True if object is a block, default is False.
        """
        return SOLFalse()

    def isNil(self):
        """
        Return True if object is nil, default is False.
        """
        return SOLFalse()

    def isBoolean(self):
        """
        Return True if object is a boolean, default is False.
        """
        return SOLFalse()


# ======================
# NIL
# ======================


class SOLNil(SOLObject):
    """
    Represents the language's nil value.
    """

    _instance = None

    def __new__(cls):
        """Create or return the singleton instance of SOLNil."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def asString(self):
        """
        Return string representation of nil.
        """
        return SOLString("nil")

    def isNil(self):
        """
        Identify this object as nil.
        """
        return SOLTrue()


# Single shared nil instance.
nil = SOLNil()


# ======================
# BOOLEAN
# ======================


class SOLBoolean(SOLObject):
    """
    Base class for boolean values (true/false).
    """

    def isBoolean(self):
        """
        Identify this object as boolean.
        """
        return SOLTrue()


class SOLTrue(SOLBoolean):
    """
    Runtime representation of boolean true.
    """

    def asString(self):
        """
        Return string representation 'true'.
        """
        return SOLString("true")

    def not_(self):
        """
        Logical negation of true is false.
        """
        return SOLFalse()

    def and_(self, other):
        """
        Logical AND.
        """
        return other.value()

    def or_(self, block):
        """
        Logical OR.
        """
        return self


class SOLFalse(SOLBoolean):
    """
    Runtime representation of boolean false.
    """

    def asString(self):
        """
        Return string representation 'false'.
        """
        return SOLString("false")

    def not_(self):
        """
        Logical negation of false is true.
        """
        return SOLTrue()

    def and_(self, block):
        """
        Logical AND.
        """
        return self

    def or_(self, other):
        """
        Logical OR.
        """
        return other.value()


# ======================
# INTEGER
# ======================


class SOLInteger(SOLObject):
    """
    Runtime representation of integer.
    """

    def __init__(self, value=0):
        self.value = int(value)

    def isNumber(self):
        """
        Identify this object as a number.
        """
        return SOLTrue()

    def plus_(self, other):
        """
        Return new SOLInteger with summed value. (addition)
        """
        return SOLInteger(self.value + other.value)

    def minus_(self, other):
        """
        Return new SOLInteger with difference. (subtraction)
        """
        return SOLInteger(self.value - other.value)

    def multiplyBy_(self, other):
        """
        Return new SOLInteger with product. (multiplication)
        """
        return SOLInteger(self.value * other.value)

    def divBy_(self, other):
        """
        Return new SOLINteger with quotient. (division)
        """
        if other.value == 0:
            raise InterpreterError(ErrorCode.INT_INVALID_ARG, "Division by zero!")
        return SOLInteger(self.value // other.value)

    def greaterThan_(self, other):
        """
        Comparison: return True if self > other else False.
        """
        return SOLTrue() if self.value > other.value else SOLFalse()

    def asString(self):
        """
        String representation of integer value.
        """
        return SOLString(str(self.value))

    def asInteger(self):
        """
        Return self as integer (identity conversion).
        """
        return self

    def equalTo_(self, other):
        """
        Only returns true if other is SOLInteger with same numeric value.
        """
        if not isinstance(other, SOLInteger):
            return SOLFalse()
        return SOLTrue() if self.value == other.value else SOLFalse()


# ======================
# STRING
# ======================


class SOLString(SOLObject):
    """
    Runtime representation of a string.
    """

    def __init__(self, value=""):
        self.value = value

    def isString(self):
        """
        Identify this object as a string.
        """
        return SOLTrue()

    def print_(self):
        """
        Print the string to standard output without adding a newline.
        """
        print(self.value, end="")
        return self

    def equalTo_(self, other):
        """
        True only if other is SOLString with identical content.
        """
        if not isinstance(other, SOLString):
            return SOLFalse()
        return SOLTrue() if self.value == other.value else SOLFalse()

    def asString(self):
        """
        Return self as a string.
        """
        return self

    def asInteger(self):
        """
        Attempt to parse the string as an integer.
        """
        try:
            return SOLInteger(int(self.value))
        except ValueError:
            return nil

    def concatenateWith_(self, other):
        """
        Concatenate with another SOLString. If the other operand is not a string,
        return nil to indicate an invalid operation.
        """
        if not isinstance(other, SOLString):
            return nil
        return SOLString(self.value + other.value)

    def startsWith_endsBefore_(self, a, b):
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

    def length(self):
        """
        Return the length of the string as SOLInteger.
        """
        return SOLInteger(len(self.value))
