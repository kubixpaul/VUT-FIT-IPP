from interpreter.error_codes import ErrorCode


# ======================
# BASE OBJECT
# ======================

class SOLObject:
    def identicalTo_(self, other):
        return SOLTrue() if self is other else SOLFalse()

    def equalTo_(self, other):
        if hasattr(self, "value") and hasattr(other, "value"):
            return SOLTrue() if self.value == other.value else SOLFalse()
        return self.identicalTo_(other)

    def asString(self):
        return SOLString("")

    def isNumber(self):
        return SOLFalse()

    def isString(self):
        return SOLFalse()

    def isBlock(self):
        return SOLFalse()

    def isNil(self):
        return SOLFalse()

    def isBoolean(self):
        return SOLFalse()


# ======================
# NIL (singleton)
# ======================

class SOLNil(SOLObject):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def asString(self):
        return SOLString("nil")

    def isNil(self):
        return SOLTrue()


nil = SOLNil()


# ======================
# BOOLEAN
# ======================

class SOLBoolean(SOLObject):
    def isBoolean(self):
        return SOLTrue()


class SOLTrue(SOLBoolean):
    def asString(self):
        return SOLString("true")

    def not_(self):
        return SOLFalse()

    def and_(self, block):
        return block.value()

    def or_(self, block):
        return self

    def ifTrue_ifFalse_(self, t_block, f_block):
        return t_block.value()


class SOLFalse(SOLBoolean):
    def asString(self):
        return SOLString("false")

    def not_(self):
        return SOLTrue()

    def and_(self, block):
        return self

    def or_(self, block):
        return block.value()

    def ifTrue_ifFalse_(self, t_block, f_block):
        return f_block.value()


# ======================
# INTEGER
# ======================

class SOLInteger(SOLObject):
    def __init__(self, value=0):
        self.value = int(value)

    def isNumber(self):
        return SOLTrue()

    def plus_(self, other):
        return SOLInteger(self.value + other.value)

    def minus_(self, other):
        return SOLInteger(self.value - other.value)

    def multiplyBy_(self, other):
        return SOLInteger(self.value * other.value)

    def divBy_(self, other):
        if other.value == 0:
            ErrorCode.fire(ErrorCode.SEM_ZERO_DIV, "Division by zero!")
        return SOLInteger(self.value // other.value)

    def greaterThan_(self, other):
        return SOLTrue() if self.value > other.value else SOLFalse()

    def asString(self):
        return SOLString(str(self.value))

    def asInteger(self):
        return self


# ======================
# STRING
# ======================

class SOLString(SOLObject):
    def __init__(self, value=""):
        self.value = value

    def isString(self):
        return SOLTrue()

    def print(self):
        print(self.value, end="")
        return self

    def equalTo_(self, other):
        return SOLTrue() if self.value == other.value else SOLFalse()

    def asString(self):
        return self

    def asInteger(self):
        try:
            return SOLInteger(int(self.value))
        except:
            return nil

    def concatenateWith_(self, other):
        if not isinstance(other, SOLString):
            return nil
        return SOLString(self.value + other.value)

    def length(self):
        return SOLInteger(len(self.value))


# ======================
# BLOCK
# ======================

class SOLBlock(SOLObject):
    def __init__(self, interpreter, block_ast, parent_frame):
        self.interpreter = interpreter
        self.block_ast = block_ast
        self.parent_frame = parent_frame

    def isBlock(self):
        return SOLTrue()

    def value(self):
        return self.interpreter.execute_block(self.block_ast, self.parent_frame)

    def value_(self, arg):
        new_frame = dict(self.parent_frame)
        param = self.block_ast.parameters[0].name
        new_frame[param] = arg
        return self.interpreter.execute_block(self.block_ast, new_frame)

    def whileTrue_(self, body_block):
        result = nil
        while self.value().value is True:
            result = body_block.value()
        return result