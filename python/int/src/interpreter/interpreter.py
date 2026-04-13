"""
This module contains the main logic of the interpreter.

IPP: You must definitely modify this file. Bend it to your will.

Author: Ondřej Ondryáš <iondryas@fit.vut.cz>
Author: Pavol Kubov <xkubovp00@fit.vut.cz>
"""

import logging
from pathlib import Path
from typing import TextIO

from lxml import etree
from lxml.etree import ParseError
from pydantic import ValidationError

import interpreter.built_in as builtins_module
from interpreter.error_codes import ErrorCode
from interpreter.exceptions import InterpreterError
from interpreter.input_model import Block, Program

logger = logging.getLogger(__name__)


class Interpreter:
    """
    The main interpreter class, responsible for loading the source file and executing the program.
    """

    def __init__(self) -> None:
        """Initialize the interpreter."""
        self.current_program: Program | None = None
        self.input_io: TextIO | None = None
        self.builtin_classes: dict = {}

    def load_program(self, source_file_path: Path) -> None:
        """
        Reads the source SOL-XML file and stores it as the target program for this interpreter.
        If any program was previously loaded, it is replaced by the new one.
        """
        logger.info("Opening source file: %s", source_file_path)
        try:
            xml_tree = etree.parse(source_file_path)
        except ParseError as e:
            raise InterpreterError(
                error_code=ErrorCode.INT_XML, message="Error parsing input XML"
            ) from e
        try:
            self.current_program = Program.from_xml_tree(xml_tree.getroot())  # type: ignore
        except ValidationError as e:
            raise InterpreterError(
                error_code=ErrorCode.INT_STRUCTURE, message="Invalid SOL-XML structure"
            ) from e

    def execute(self, input_io: TextIO) -> None:
        """
        Executes the currently loaded program, using the provided input stream as standard input.
        """
        self.input_io = input_io

        self.builtin_classes = {
            "Object": builtins_module.SOLObject,
            "Integer": builtins_module.SOLInteger,
            "String": builtins_module.SOLString,
            "Nil": builtins_module.SOLNil,
            "True": builtins_module.SOLTrue,
            "False": builtins_module.SOLFalse,
        }

        assert self.current_program is not None

        main_class = None
        for cl in self.current_program.classes:
            if cl.name == "Main":
                main_class = cl
                break
        if main_class is None:
            raise InterpreterError(ErrorCode.SEM_MAIN, "Missing Main class in program!")

        run_method = None
        for method in main_class.methods:
            if method.selector == "run":
                run_method = method
                break
        if run_method is None:
            raise InterpreterError(ErrorCode.SEM_MAIN, "Missing run method in Main!")

        seen_classes: set[str] = set()
        for cl in self.current_program.classes:
            if cl.name in seen_classes:
                msg = f"Duplicate class definition: {cl.name}"
                raise InterpreterError(ErrorCode.SEM_ERROR, msg)
            seen_classes.add(cl.name)

        main_class_instance = ClassInstance(main_class)
        self.execute_method(run_method, main_class_instance, args=None)

    def eval_expr(self, expr: object, frame: dict, current_class: object) -> object:
        """Evaluate an expression node and return its runtime value."""
        if expr.literal is not None:  # type: ignore[union-attr]
            return self.eval_literal(expr.literal)  # type: ignore[union-attr]
        if expr.var is not None:  # type: ignore[union-attr]
            return self.eval_var(expr.var, frame)  # type: ignore[union-attr]
        if expr.block is not None:  # type: ignore[union-attr]
            return BlockInstance(expr.block, frame)  # type: ignore[union-attr]
        if expr.send is not None:  # type: ignore[union-attr]
            return self.eval_send(expr.send, frame, current_class)  # type: ignore[union-attr]
        return builtins_module.nil

    def eval_literal(self, lit: object) -> object:
        """Evaluates a literal AST node and converts it into its runtime representation."""
        if lit.class_id == "Integer":  # type: ignore[union-attr]
            return builtins_module.SOLInteger(int(lit.value))  # type: ignore[union-attr]
        if lit.class_id == "String":  # type: ignore[union-attr]
            return builtins_module.SOLString(lit.value)  # type: ignore[union-attr]
        if lit.class_id == "Nil":  # type: ignore[union-attr]
            return builtins_module.nil
        if lit.class_id == "True":  # type: ignore[union-attr]
            return builtins_module.SOLTrue()
        if lit.class_id == "False":  # type: ignore[union-attr]
            return builtins_module.SOLFalse()
        if lit.class_id == "class":  # type: ignore[union-attr]
            return lit.value  # type: ignore[union-attr]
        return builtins_module.nil

    def eval_var(self, var: object, frame: dict) -> object:
        """Resolve a variable reference in the given frame."""
        name = var.name  # type: ignore[union-attr]
        if name in ("self", "super"):
            return frame[name]
        if name not in frame:
            raise InterpreterError(ErrorCode.SEM_UNDEF, f"Undefined variable: {name}!")
        return frame[name]

    def eval_send(self, send: object, frame: dict, current_class: object) -> object:
        """Evaluate a message send expression and dispatch based on receiver type."""
        is_super = (
            send.receiver.var is not None  # type: ignore[union-attr]
            and send.receiver.var.name == "super"  # type: ignore[union-attr]
        )
        receiver = self.eval_expr(send.receiver, frame, current_class)  # type: ignore[union-attr]
        args = [
            self.eval_expr(arg.expr, frame, current_class)
            for arg in send.args  # type: ignore[union-attr]
        ]

        if isinstance(receiver, str):
            return self.dispatch_class_message(
                receiver, send.selector, args, frame  # type: ignore[union-attr]
            )

        if isinstance(receiver, BlockInstance):
            return self.dispatch_block(
                receiver, send.selector, args, current_class  # type: ignore[union-attr]
            )

        if isinstance(receiver, (ClassInstance, ObjectInstance)):
            return self.dispatch_instance(
                receiver, send.selector, args, current_class, is_super  # type: ignore[union-attr]
            )

        result = self.dispatch_builtin(
            receiver, send.selector, args, current_class  # type: ignore[union-attr]
        )
        if result is not None:
            return result

        raise InterpreterError(
            ErrorCode.INT_DNU,
            f"Does not understand message '{send.selector}'!"  # type: ignore[union-attr]
        )

    def dispatch_class_message(
        self, class_name: str, selector: str, args: list, frame: dict
    ) -> object:
        """Handle messages sent to classes (class-side messages)."""
        if selector == "new":
            if class_name in self.builtin_classes:
                cls = self.builtin_classes[class_name]
                if class_name == "Integer":
                    return cls(0)
                if class_name == "String":
                    return cls("")
                if class_name == "Nil":
                    return builtins_module.nil
                if class_name == "Object":
                    return ObjectInstance()
                return cls()

            if class_name == "Block":
                empty_block = Block(arity=0, parameters=[], assigns=[])
                return BlockInstance(empty_block, frame)

            assert self.current_program is not None
            for cl in self.current_program.classes:
                if class_name == cl.name:
                    return ClassInstance(cl)

        if selector == "from:" and len(args) == 1:
            return self.dispatch_from(class_name, args[0])

        if selector == "read" and class_name == "String":
            assert self.input_io is not None
            line = self.input_io.readline()
            if line.endswith("\n"):
                line = line[:-1]
            return builtins_module.SOLString(line)

        raise InterpreterError(
            ErrorCode.SEM_UNDEF, f"Unknown class message: {class_name} {selector}"
        )

    def dispatch_from(self, class_name: str, obj: object) -> object:
        """Convert obj to an instance of class_name where possible."""
        if class_name == "Integer":
            if not hasattr(obj, "value") or not isinstance(obj.value, int):  # type: ignore[union-attr]
                raise InterpreterError(
                    ErrorCode.INT_INVALID_ARG,
                    "from: requires Integer-compatible object",
                )
            return builtins_module.SOLInteger(obj.value)  # type: ignore[union-attr]

        if class_name == "String":
            if not hasattr(obj, "value") or not isinstance(obj.value, str):  # type: ignore[union-attr]
                raise InterpreterError(
                    ErrorCode.INT_INVALID_ARG,
                    "from: requires String-compatible object",
                )
            return builtins_module.SOLString(obj.value)  # type: ignore[union-attr]

        if class_name == "Nil":
            return builtins_module.nil

        if class_name == "Object":
            new_inst = ObjectInstance()
            if isinstance(obj, (ClassInstance, ObjectInstance)):
                new_inst.attributes = dict(obj.attributes)
            return new_inst

        assert self.current_program is not None
        for cl in self.current_program.classes:
            if class_name == cl.name:
                new_inst = ClassInstance(cl)
                if isinstance(obj, ClassInstance):
                    new_inst.attributes = dict(obj.attributes)
                if hasattr(obj, "value"):
                    new_inst.value = obj.value  # type: ignore[union-attr]
                return new_inst

        raise InterpreterError(ErrorCode.SEM_UNDEF, f"Unknown class: {class_name}")

    def dispatch_block(
        self, receiver: BlockInstance, selector: str, args: list, current_class: object
    ) -> object:
        """Handle messages sent to block instances."""
        if selector == "isBlock":
            return builtins_module.SOLTrue()

        if selector == "whileTrue:" and len(args) == 1:
            result: object = builtins_module.nil
            while True:
                cond = self.execute_block(receiver, current_class, [])
                if not isinstance(cond, builtins_module.SOLTrue):
                    break
                result = self.execute_block(args[0], current_class, [])
            return result

        if selector == "value":
            return self.execute_block(receiver, current_class, [])

        if selector == "value:" and len(args) == 1:
            return self.execute_block(receiver, current_class, args)

        if selector == "value:value:" and len(args) == 2:
            return self.execute_block(receiver, current_class, args)

        return builtins_module.nil

    def dispatch_instance(
        self,
        receiver: object,
        selector: str,
        args: list,
        current_class: object,
        is_super: bool,
    ) -> object:
        """Dispatch a message to an instance."""
        assert self.current_program is not None

        if is_super:
            method = receiver.find_method_from_parent(  # type: ignore[union-attr]
                selector, self.current_program.classes, current_class
            )
        else:
            method = receiver.find_method(  # type: ignore[union-attr]
                selector, self.current_program.classes
            )

        if method is not None:
            return self.execute_method(method, receiver, args)

        base_name = receiver.get_base(self.current_program.classes)  # type: ignore[union-attr]
        builtin_class = self.builtin_classes[base_name]
        result = self.dispatch_builtin(builtin_class(), selector, args, current_class)
        if result is not None:
            return result

        return self.attribute_fallback(receiver, selector, args)

    def dispatch_builtin(
        self, receiver: object, selector: str, args: list, current_class: object
    ) -> object:
        """Dispatch messages implemented by builtin runtime objects."""
        result = self.dispatch_boolean(receiver, selector, args, current_class)
        if result is not None:
            return result
        result = self.dispatch_integer(receiver, selector, args, current_class)
        if result is not None:
            return result
        return self.dispatch_generic(receiver, selector, args)

    def dispatch_boolean(
        self, receiver: object, selector: str, args: list, current_class: object
    ) -> object:
        """Handle boolean-specific messages."""
        if (
            isinstance(receiver, (builtins_module.SOLTrue, builtins_module.SOLFalse))
            and selector == "ifTrue:ifFalse:"
            and len(args) == 2
        ):
            if isinstance(receiver, builtins_module.SOLTrue):
                return self.execute_block(args[0], current_class, [])
            return self.execute_block(args[1], current_class, [])

        if selector == "and:" and len(args) == 1:
            if isinstance(receiver, builtins_module.SOLFalse):
                return builtins_module.SOLFalse()
            if isinstance(args[0], BlockInstance):
                return self.execute_block(args[0], current_class, [])

        if selector == "or:" and len(args) == 1:
            if isinstance(receiver, builtins_module.SOLTrue):
                return builtins_module.SOLTrue()
            if isinstance(args[0], BlockInstance):
                return self.execute_block(args[0], current_class, [])

        return None

    def dispatch_integer(
        self, receiver: object, selector: str, args: list, current_class: object
    ) -> object:
        """Handle integer-specific messages."""
        if (
            isinstance(receiver, builtins_module.SOLInteger)
            and selector == "timesRepeat:"
            and len(args) == 1
        ):
            result: object = builtins_module.nil
            for i in range(1, receiver.value + 1):
                result = self.execute_block(
                    args[0], current_class, [builtins_module.SOLInteger(i)]
                )
            return result
        return None

    def dispatch_generic(self, receiver: object, selector: str, args: list) -> object:
        """Handle generic builtin messages via getattr."""
        if selector == "isBlock":
            return builtins_module.SOLFalse()
        method_name = selector.replace(":", "_")
        if selector == "print":
            method_name = "print_"
        if selector == "not":
            method_name = "not_"
        method = getattr(receiver, method_name, None)
        if method is not None:
            return method(*args)
        return None

    def attribute_fallback(self, receiver: object, selector: str, args: list) -> object:
        """Handle attribute access and assignment on instances."""
        if len(args) == 0:
            val = receiver.attributes.get(selector)  # type: ignore[union-attr]
            if val is None:
                raise InterpreterError(
                    ErrorCode.INT_DNU, f"No method or attribute '{selector}'!"
                )
            return val

        if len(args) == 1:
            attr_name = selector.rstrip(":")
            collision = receiver.find_method(  # type: ignore[union-attr]
                attr_name, self.current_program.classes  # type: ignore[union-attr]
            )
            if collision is not None:
                raise InterpreterError(
                    ErrorCode.INT_INST_ATTR,
                    f"Attribute '{attr_name}' collides with method!",
                )
            assert self.current_program is not None
            base_name = receiver.get_base(self.current_program.classes)  # type: ignore[union-attr]
            builtin_class = self.builtin_classes[base_name]

            if getattr(builtin_class(), attr_name, None) is not None:
                raise InterpreterError(
                    ErrorCode.INT_INST_ATTR,
                    f"Attribute '{attr_name}' collides with builtin method!",
                )

            receiver.attributes[attr_name] = args[0]  # type: ignore[union-attr]
            return receiver

        raise InterpreterError(ErrorCode.INT_DNU, f"No method '{selector}'!")

    def execute_method(self, method: object, current_class: object, args: list | None) -> object:
        """Execute a method block."""
        if args is None:
            args = []
        frame: dict = {}
        frame["self"] = current_class
        frame["super"] = current_class

        method_block = BlockInstance(method.block, frame)  # type: ignore[union-attr]
        return self.execute_block(method_block, current_class, args)

    def execute_block(
        self, block_instance: BlockInstance, current_class: object, args: list
    ) -> object:
        """Execute a block instance with given arguments."""
        frame = dict(block_instance.parent_frame)

        params = block_instance.block.parameters
        if len(params) != len(args):
            raise InterpreterError(ErrorCode.INT_DNU, "Block arity mismatch!")

        param_names = {p.name for p in params}
        for param, arg in zip(params, args, strict=True):
            frame[param.name] = arg

        result: object = builtins_module.nil
        for stmt in block_instance.block.assigns:
            if stmt.target.name in param_names:
                msg = f"Assignment to parameter {stmt.target.name}"
                raise InterpreterError(ErrorCode.SEM_COLLISION, msg)
            result = self.eval_expr(stmt.expr, frame, current_class)
            frame[stmt.target.name] = result
        return result


class ClassInstance:
    """Runtime representation of a user-defined class instance."""

    def __init__(self, cl: object) -> None:
        """Initialize with the class definition."""
        self.cl = cl
        self.cl_name = cl.name  # type: ignore[union-attr]
        self.attributes: dict = {}

    def find_method(self, selector: str, all_classes: list) -> object:
        """Find a method in this class or its ancestors."""
        current = self.cl
        while current is not None:
            for method in current.methods:  # type: ignore[union-attr]
                if method.selector == selector:
                    return method
            parent = current.parent  # type: ignore[union-attr]
            current = None
            for cl in all_classes:
                if cl.name == parent:
                    current = cl
                    break
        return None

    def find_method_from_parent(
        self, selector: str, all_classes: list, from_class: object
    ) -> object:
        """Find a method starting from the parent of from_class."""
        start_class = None
        for cl in all_classes:
            if cl.name == from_class.cl_name:  # type: ignore[union-attr]
                start_class = cl
                break

        if start_class is None:
            return None

        start_parent = start_class.parent  # type: ignore[union-attr]
        parent_class = None

        for cl in all_classes:
            if cl.name == start_parent:
                parent_class = cl
                break

        while parent_class is not None:
            for method in parent_class.methods:  # type: ignore[union-attr]
                if method.selector == selector:
                    return method
            parent = parent_class.parent  # type: ignore[union-attr]
            parent_class = None
            for cl in all_classes:
                if cl.name == parent:
                    parent_class = cl
                    break
        return None

    def get_base(self, all_classes: list) -> str:
        """Determine the builtin base class name for this instance."""
        current = self.cl
        base_names = {"Object", "Integer", "String", "Nil", "True", "False", "Block"}

        while current is not None:
            if current.parent in base_names:  # type: ignore[union-attr]
                return current.parent  # type: ignore[union-attr]
            parent_name = current.parent  # type: ignore[union-attr]
            current = None
            for cl in all_classes:
                if cl.name == parent_name:
                    current = cl
                    break

        return "Object"


class BlockInstance:
    """Runtime representation of a block (closure)."""

    def __init__(self, block: object, parent_frame: dict) -> None:
        """Initialize with block AST and captured frame."""
        self.block = block
        self.parent_frame = parent_frame


class ObjectInstance:
    """Minimal runtime object for the builtin Object class."""

    def __init__(self) -> None:
        """Initialize with empty attributes."""
        self.cl_name = "Object"
        self.attributes: dict = {}

    def find_method(self, selector: str, all_classes: list) -> None:
        """Object has no user-defined methods; always return None."""
        return

    def find_method_from_parent(
        self, selector: str, all_classes: list, from_class: object
    ) -> None:
        """Object has no parent methods; always return None."""
        return

    def get_base(self, all_classes: list) -> str:
        """Base for Object is always Object."""
        return "Object"
