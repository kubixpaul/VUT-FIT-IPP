"""
This module contains the main logic of the interpreter.

IPP: You must definitely modify this file. Bend it to your will.

Author: Ondřej Ondryáš <iondryas@fit.vut.cz>
Author: Pavol Kubov <xkubovp00@fit.vut.cz>
"""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO, cast

from lxml import etree
from lxml.etree import ParseError
from pydantic import ValidationError

import interpreter.built_in as built_in
from interpreter.error_codes import ErrorCode
from interpreter.exceptions import InterpreterError
from interpreter.input_model import Block, Program

logger = logging.getLogger(__name__)


class Interpreter:
    """
    The main interpreter class, responsible for loading the source file and executing the program.
    """

    current_program: Program | None

    def __init__(self) -> None:
        self.current_program = None

    def load_program(self, source_file_path: Path) -> None:
        """
        Reads the source SOL-XML file and stores it as the target program for this interpreter.
        If any program was previously loaded, it is replaced by the new one.

        IPP: If you wish to run static checks on the program before execution, this is a good place
             to call them from.
        """
        logger.info("Opening source file: %s", source_file_path)
        try:
            xml_tree = etree.parse(source_file_path)
        except ParseError as e:
            raise InterpreterError(
                error_code=ErrorCode.INT_XML, message="Error parsing input XML"
            ) from e
        try:
            # xml_tree.getroot() has lxml type; cast to Any to satisfy pydantic model method
            self.current_program = Program.from_xml_tree(cast(Any, xml_tree.getroot()))
        except ValidationError as e:
            raise InterpreterError(
                error_code=ErrorCode.INT_STRUCTURE, message="Invalid SOL-XML structure"
            ) from e

    def execute(self, input_io: TextIO) -> None:
        """
        Executes the currently loaded program, using the provided input stream as standard input.
        """
        if self.current_program is None:
            raise InterpreterError(ErrorCode.SEM_MAIN, "No program loaded!")

        self.input_io = input_io

        # Map names of builtin classes to their implementation classes/constructors.
        self.builtin_classes: dict[str, Any] = {
            "Object": built_in.SOLObject,
            "Integer": built_in.SOLInteger,
            "String": built_in.SOLString,
            "Nil": built_in.SOLNil,
            "True": built_in.SOLTrue,
            "False": built_in.SOLFalse,
        }

        # Locate Main class
        main_class = None
        for cl in self.current_program.classes:
            if cl.name == "Main":
                main_class = cl
                break
        if main_class is None:
            raise InterpreterError(ErrorCode.SEM_MAIN, "Missing Main class in program!")

        # Locate run method on Main
        run_method = None
        for method in main_class.methods:
            if method.selector == "run":
                run_method = method
                break
        if run_method is None:
            raise InterpreterError(ErrorCode.SEM_MAIN, "Missing run method in Main!")

        # Ensures no class has a duplicit definition
        seen_classes: set[str] = set()
        for cl in self.current_program.classes:
            if cl.name in seen_classes:
                raise InterpreterError(
                    ErrorCode.SEM_ERROR, f"Duplicate class definition: {cl.name}"
                )
            seen_classes.add(cl.name)

        main_class_instance = ClassInstance(main_class)
        self.execute_method(run_method, main_class_instance, args=None)

    def eval_expr(self, expr: Any, frame: dict[str, Any], current_class: Any) -> Any:
        """
        Evaluate an expression node and return its runtime value.
        """
        if expr.literal is not None:
            return self.eval_literal(expr.literal)
        if expr.var is not None:
            return self.eval_var(expr.var, frame)
        if expr.block is not None:
            return BlockInstance(expr.block, frame)
        if expr.send is not None:
            return self.eval_send(expr.send, frame, current_class)

        # Fallback to nil if expression is empty or unrecognized
        return built_in.nil

    def eval_literal(self, lit: Any) -> Any:
        """
        Evaluates a literal AST node and converts it into its runtime representation.
        """
        if lit.class_id == "Integer":
            return built_in.SOLInteger(int(lit.value))
        if lit.class_id == "String":
            return built_in.SOLString(lit.value)
        if lit.class_id == "Nil":
            return built_in.nil
        if lit.class_id == "True":
            return built_in.SOLTrue()
        if lit.class_id == "False":
            return built_in.SOLFalse()
        if lit.class_id == "class":
            # Returns the class name to be used by messages
            return lit.value
        return built_in.nil

    def eval_var(self, var: Any, frame: dict[str, Any]) -> Any:
        """
        Resolve a variable reference in the given frame.
        """
        name = var.name
        # Special case for self, super stored in var node
        if name in ("self", "super"):
            return frame[name]
        if name not in frame:
            raise InterpreterError(ErrorCode.SEM_UNDEF, f"Undefined variable: {name}!")
        return frame[name]

    def eval_send(self, send: Any, frame: dict[str, Any], current_class: Any) -> Any:
        """
        Evaluate a message send (method call) expression and dispatch based on receiver type.
        """
        is_super = send.receiver.var is not None and send.receiver.var.name == "super"
        receiver = self.eval_expr(send.receiver, frame, current_class)
        args = [self.eval_expr(arg.expr, frame, current_class) for arg in send.args]

        # If receiver is a class name
        if isinstance(receiver, str):
            return self.dispatch_class_message(receiver, send.selector, args, frame)

        # If receiver is a block instance
        if isinstance(receiver, BlockInstance):
            return self.dispatch_block(receiver, send.selector, args, current_class)

        # If receiver is an object instance
        if isinstance(receiver, ObjectInstance):
            return self.dispatch_instance(receiver, send.selector, args, current_class, is_super)

        # If receiver is a class instance
        if isinstance(receiver, ClassInstance):
            return self.dispatch_instance(receiver, send.selector, args, current_class, is_super)

        # Lastly checks whether receiver is a built-in class
        result = self.dispatch_builtin(receiver, send.selector, args, current_class)
        if result is not None:
            return result

        raise InterpreterError(
            ErrorCode.INT_DNU, f"Does not understand message '{send.selector}'!"
        )

    def dispatch_class_message(
        self, class_name: str, selector: str, args: Sequence[Any], frame: dict[str, Any]
    ) -> Any:
        """
        Handle messages sent to classes (class-side messages).
        """
        if selector == "new":
            # Built-in classes, construct appropriate default instances
            if class_name in self.builtin_classes:
                cls = self.builtin_classes[class_name]
                if class_name == "Integer":
                    return cls(0)
                if class_name == "String":
                    return cls("")
                if class_name == "Nil":
                    return built_in.nil
                if class_name == "Object":
                    return ObjectInstance()
                return cls()

            # Special built-in case, held in 'BlockInstance' instead of being
            # part of the builtin_classes
            # Creates an empty, default, block instance
            if class_name == "Block":
                empty_block = Block(arity=0, parameters=[], assigns=[])
                return BlockInstance(empty_block, frame)

            # User defined classes, find class definition and instantiate
            assert self.current_program is not None
            for cl in self.current_program.classes:
                if class_name == cl.name:
                    return ClassInstance(cl)

        if selector == "from:" and len(args) == 1:
            return self.dispatch_from(class_name, args[0])

        if selector == "read" and class_name == "String":
            # Read a line from the provided input stream and return as SOLString
            line = self.input_io.readline()
            if line.endswith("\n"):
                line = line[:-1]
            return built_in.SOLString(line)

        # Ensure explicit return for all code paths
        return built_in.nil

    def dispatch_from(self, class_name: str, obj: Any) -> Any:
        """
        Convert 'obj' to an instance of 'class_name' where possible.
        """
        if class_name == "Integer":
            if not hasattr(obj, "value") or not isinstance(obj.value, int):
                raise InterpreterError(
                    ErrorCode.INT_INVALID_ARG, "from: requires Integer-compatible object"
                )
            return built_in.SOLInteger(obj.value)

        if class_name == "String":
            if not hasattr(obj, "value") or not isinstance(obj.value, str):
                raise InterpreterError(
                    ErrorCode.INT_INVALID_ARG, "from: requires String-compatible object"
                )
            return built_in.SOLString(obj.value)

        if class_name == "Nil":
            return built_in.nil

        if class_name == "Object":
            obj_inst = ObjectInstance()
            if isinstance(obj, (ClassInstance, ObjectInstance)):
                # Copy attributes from source object
                obj_inst.attributes = dict(obj.attributes)
            return obj_inst

        # Instantiate user defined classes and copy attributes / value if applicable
        assert self.current_program is not None
        for cl in self.current_program.classes:
            if class_name == cl.name:
                class_inst = ClassInstance(cl)
                if isinstance(obj, ClassInstance):
                    class_inst.attributes = dict(obj.attributes)
                if hasattr(obj, "value"):
                    class_inst.value = obj.value
                return class_inst

        raise InterpreterError(ErrorCode.SEM_UNDEF, f"Unknown class: {class_name}")

    def dispatch_block(
        self, receiver: BlockInstance, selector: str, args: Sequence[Any], current_class: Any
    ) -> Any:
        """
        Handle messages sent to block instances.
        """
        if selector == "isBlock":
            return built_in.SOLTrue()

        if selector == "whileTrue:" and len(args) == 1:
            result = built_in.nil
            while True:
                cond = self.execute_block(receiver, current_class, [])
                if not isinstance(cond, built_in.SOLTrue):
                    break
                result = self.execute_block(args[0], current_class, [])
            return result

        if selector == "value":
            return self.execute_block(receiver, current_class, [])

        if selector == "value:" and len(args) == 1:
            return self.execute_block(receiver, current_class, args)

        if selector == "value:value:" and len(args) == 2:
            return self.execute_block(receiver, current_class, args)

        return built_in.nil

    def dispatch_instance(
        self,
        receiver: Any,
        selector: str,
        args: Sequence[Any],
        current_class: Any,
        is_super: bool,
    ) -> Any:
        """
        Dispatch a message to an instance (user-defined class instance or object).
        """
        # Handles the receiver 'super' differently to comply with its function
        if is_super:
            # 'super' starts searching from parent class
            assert self.current_program is not None
            method = receiver.find_method_from_parent(
                selector, self.current_program.classes, current_class
            )
        else:
            assert self.current_program is not None
            method = receiver.find_method(selector, self.current_program.classes)

        if method is not None:
            return self.execute_method(method, receiver, args)

        # If no user defined method was found, try builtin behavior for the receiver's base class
        assert self.current_program is not None
        base_name = receiver.get_base(self.current_program.classes)
        builtin_class = self.builtin_classes[base_name]
        result = self.dispatch_builtin(builtin_class(), selector, args, current_class)
        if result is not None:
            return result

        # As a last resort try attribute fallback
        return self.attribute_fallback(receiver, selector, args)

    def dispatch_special_cases(
        self, receiver: Any, selector: str, args: Sequence[Any], current_class: Any
    ) -> Any | None:
        """
        Handle special-case builtin behaviors that interact with BlockInstance.
        Returns a value or None if not handled.
        """
        # Boolean ifTrue ifFalse
        if (
            isinstance(receiver, (built_in.SOLTrue, built_in.SOLFalse))
            and selector == "ifTrue:ifFalse:"
            and len(args) == 2
        ):
            if isinstance(receiver, built_in.SOLTrue):
                return self.execute_block(args[0], current_class, [])
            return self.execute_block(args[1], current_class, [])

        # Boolean and:
        if selector == "and:" and len(args) == 1:
            if isinstance(receiver, built_in.SOLFalse):
                return built_in.SOLFalse()
            if isinstance(args[0], BlockInstance):
                return self.execute_block(args[0], current_class, [])

        # Boolean or:
        if selector == "or:" and len(args) == 1:
            if isinstance(receiver, built_in.SOLTrue):
                return built_in.SOLTrue()
            if isinstance(args[0], BlockInstance):
                return self.execute_block(args[0], current_class, [])

        # Integer timesRepeat:
        if (
            isinstance(receiver, built_in.SOLInteger)
            and selector == "timesRepeat:"
            and len(args) == 1
        ):
            result = built_in.nil
            for i in range(1, receiver.value + 1):
                result = self.execute_block(args[0], current_class, [built_in.SOLInteger(i)])
            return result

        return None

    def dispatch_builtin(
        self, receiver: Any, selector: str, args: Sequence[Any], current_class: Any
    ) -> Any | None:
        """
        Dispatch messages implemented by builtin runtime objects.
        """
        # Delegate special intertwined cases to helper
        special = self.dispatch_special_cases(receiver, selector, args, current_class)
        if special is not None:
            return special

        # If the method is found here, it automatically doesn't
        # belong to a Block => always returns False
        if selector == "isBlock":
            return built_in.SOLFalse()

        method_name = selector.replace(":", "_")
        # Adds a '_' at the end of 'print' and 'not' because they are a part of python
        if selector == "print":
            method_name = "print_"

        if selector == "not":
            method_name = "not_"

        # Looks for the method in built-in methods on built-in classes
        method = getattr(receiver, method_name, None)
        if method is not None:
            return method(*args)

        return None

    def attribute_fallback(self, receiver: Any, selector: str, args: Sequence[Any]) -> Any:
        """
        Handle attribute access and attribute assignment on instances.
        """

        # Looks for an attribute in instace
        if len(args) == 0:
            val = receiver.attributes.get(selector)
            if val is None:
                raise InterpreterError(ErrorCode.INT_DNU, f"No method or attribute '{selector}'!")
            return val

        # Tries to create an attribute with value args[0]
        if len(args) == 1:
            attr_name = selector.rstrip(":")
            # Looks for whether the name belongs to a method in the instance
            assert self.current_program is not None
            collision = receiver.find_method(attr_name, self.current_program.classes)
            if collision is not None:
                raise InterpreterError(
                    ErrorCode.INT_INST_ATTR, f"Attribute '{attr_name}' collides with method!"
                )
            base_name = receiver.get_base(self.current_program.classes)
            builtin_class = self.builtin_classes[base_name]

            # Looks for whether the name belongs to a built-in method
            if getattr(builtin_class(), attr_name, None) is not None:
                raise InterpreterError(
                    ErrorCode.INT_INST_ATTR,
                    f"Attribute '{attr_name}' collides with builtin method!",
                )

            # Sets the attribute with said name to value stored in args[0]
            receiver.attributes[attr_name] = args[0]
            return receiver

        # If there is more than 1 argument automatically assumes an error.
        raise InterpreterError(ErrorCode.INT_DNU, f"No method '{selector}!'")

    def execute_method(self, method: Any, current_class: Any, args: Sequence[Any] | None) -> Any:
        """
        Execute a method block.
        """
        if args is None:
            args_list: Sequence[Any] = []
        else:
            args_list = args
        # Create a fresh frame for method execution and set self / super
        frame: dict[str, Any] = {}
        frame["self"] = current_class
        frame["super"] = current_class

        # Wrap the method block into a BlockInstance with the method's frame
        method_block = BlockInstance(method.block, frame)

        # Execute the block and return its result
        return self.execute_block(method_block, current_class, args_list)

    def execute_block(
        self,
        block_instance: BlockInstance,
        current_class: Any,
        args: Sequence[Any],
    ) -> Any:
        """
        Execute a block instance with given arguments.
        """

        # Start with a copy of the parent frame to create a new local frame
        frame: dict[str, Any] = dict(block_instance.parent_frame)

        params = block_instance.block.parameters
        if len(params) != len(args):
            raise InterpreterError(ErrorCode.INT_DNU, "Block arity mismatch!")

        # Prevent assignments to parameters by tracking parameter names
        param_names = {p.name for p in params}
        for param, arg in zip(params, args, strict=True):
            frame[param.name] = arg

        result: Any = built_in.nil
        # Execute each assignment (statement) in the block sequentially
        for stmt in block_instance.block.assigns:
            if stmt.target.name in param_names:
                raise InterpreterError(
                    ErrorCode.SEM_COLLISION, f"Assignment to parameter {stmt.target.name}"
                )
            result = self.eval_expr(stmt.expr, frame, current_class)
            frame[stmt.target.name] = result
        return result


class ClassInstance:
    """Runtime representation of a user-defined class instance."""

    def __init__(self, cl: Any) -> None:
        self.cl = cl
        self.cl_name: str = cl.name
        self.attributes: dict[str, Any] = {}
        # Allow instances to carry a generic 'value' when created via dispatch_from
        self.value: Any = None

    def find_method(self, selector: str, all_classes: Sequence[Any]) -> Any | None:
        """
        Find a method with the name stored in 'selector' in this class or its ancestors.
        """
        current = self.cl
        while current is not None:
            for method in current.methods:
                if method.selector == selector:
                    return method
            parent = current.parent
            current = None
            for cl in all_classes:
                if cl.name == parent:
                    current = cl
                    break
        return None

    def find_method_from_parent(
        self,
        selector: str,
        all_classes: Sequence[Any],
        from_class: Any,
    ) -> Any | None:
        """
        Find a method with 'selector' starting from the parent of 'from_class'.
        """
        start_class = None
        for cl in all_classes:
            if cl.name == from_class.cl_name:
                start_class = cl
                break

        if start_class is None:
            return None

        start_parent = start_class.parent

        parent_class = None

        for cl in all_classes:
            if cl.name == start_parent:
                parent_class = cl
                break

        while parent_class is not None:
            for method in parent_class.methods:
                if method.selector == selector:
                    return method
            parent = parent_class.parent
            parent_class = None
            for cl in all_classes:
                if cl.name == parent:
                    parent_class = cl
                    break
        return None

    def get_base(self, all_classes: Sequence[Any]) -> str:
        """
        Determine the builtin base class name for this instance.
        """
        current = self.cl
        base_names = {"Object", "Integer", "String", "Nil", "True", "False", "Block"}

        while current is not None:
            if current.parent in base_names:
                # current.parent may be typed as Any
                return cast(str, current.parent)

            parent_name = current.parent
            current = None

            for cl in all_classes:
                if cl.name == parent_name:
                    current = cl
                    break

        return "Object"


class BlockInstance:
    """
    Runtime representation of a block (closure).
    """

    def __init__(self, block: Block, parent_frame: dict[str, Any]) -> None:
        self.block = block
        self.parent_frame = parent_frame


class ObjectInstance:
    """Minimal runtime object for the builtin Object class."""

    def __init__(self) -> None:
        self.cl_name: str = "Object"
        self.attributes: dict[str, Any] = {}

    def find_method(self, selector: str, all_classes: Sequence[Any]) -> None:
        """
        Object has no methods; always return None.
        """
        return

    def find_method_from_parent(
        self, selector: str, all_classes: Sequence[Any], from_class: object
    ) -> None:
        """
        Object has no parent methods; always return None.
        """
        return

    def get_base(self, all_classes: Sequence[Any]) -> str:
        """
        Base for an Object is always Object.
        """
        return "Object"
