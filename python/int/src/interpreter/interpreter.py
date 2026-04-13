"""
This module contains the main logic of the interpreter.

IPP: You must definitely modify this file. Bend it to your will.

Author: Ondřej Ondryáš <iondryas@fit.vut.cz>
Author:
"""

import logging
from pathlib import Path
from typing import TextIO

from lxml import etree
from lxml.etree import ParseError
from pydantic import ValidationError

from interpreter.error_codes import ErrorCode
from interpreter.exceptions import InterpreterError
from interpreter.input_model import Program, Block
import interpreter.built_in as Builtins

logger = logging.getLogger(__name__)

class Interpreter:
    """
    The main interpreter class, responsible for loading the source file and executing the program.
    """

    def __init__(self) -> None:
        self.current_program: Program | None = None

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
            "Object": Builtins.SOLObject,
            "Integer": Builtins.SOLInteger,
            "String": Builtins.SOLString,
            "Nil": Builtins.SOLNil,
            "True": Builtins.SOLTrue,
            "False": Builtins.SOLFalse
        }

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
        
        seen_classes = set()
        for cl in self.current_program.classes:
            if cl.name in seen_classes:
                raise InterpreterError(ErrorCode.SEM_ERROR, f"Duplicate class definition: {cl.name}")
            seen_classes.add(cl.name)


        main_class_instance = ClassInstance(main_class)
        self.execute_method(run_method, main_class_instance, args=None)

    def eval_expr(self, expr, frame, current_class):
        if expr.literal is not None:
            return self.eval_literal(expr.literal)
        if expr.var is not None:
            return self.eval_var(expr.var, frame)
        if expr.block is not None:
            return BlockInstance(expr.block, frame)
        if expr.send is not None:
            return self.eval_send(expr.send, frame, current_class)
        return Builtins.nil
    
    def eval_literal(self, lit):
        if lit.class_id == "Integer":
            return Builtins.SOLInteger(int(lit.value))
        if lit.class_id == "String":
            return Builtins.SOLString(lit.value)
        if lit.class_id == "Nil":
            return Builtins.nil
        if lit.class_id == "True":
            return Builtins.SOLTrue()
        if lit.class_id == "False":
            return Builtins.SOLFalse()
        if lit.class_id == "class":
            return lit.value
        return Builtins.nil
    
    def eval_var(self, var, frame):
        name = var.name
        if name in ("self", "super"):
            return frame[name]
        if name not in frame:
            raise InterpreterError(ErrorCode.SEM_UNDEF, f"Undefined variable: {name}!")
        return frame[name]
    
    def eval_send(self, send, frame, current_class):
        is_super = (send.receiver.var is not None and send.receiver.var.name == "super")
        receiver = self.eval_expr(send.receiver, frame, current_class)
        args = [self.eval_expr(arg.expr, frame, current_class) for arg in send.args]

        # class messages
        if isinstance(receiver, str):
            return self.dispatch_class_message(receiver, send.selector, args, frame)

        # block messages
        if isinstance(receiver, BlockInstance):
            return self.dispatch_block(receiver, send.selector, args, current_class)

        if isinstance(receiver, (ClassInstance, ObjectInstance)):
            return self.dispatch_instance(receiver, send.selector, args, current_class, is_super)

        # instance messages
        if isinstance(receiver, ClassInstance):
            return self.dispatch_instance(receiver, send.selector, args, current_class, is_super)

        # builtin messages
        result = self.dispatch_builtin(receiver, send.selector, args, current_class)
        if result is not None:
            return result

        raise InterpreterError(ErrorCode.INT_DNU, f"Does not understand message '{send.selector}'!")
    
    def dispatch_class_message(self, class_name, selector, args, frame):
        if selector == "new":
            if class_name in self.builtin_classes:
                cls = self.builtin_classes[class_name]
                if class_name == "Integer":
                    return cls(0)
                if class_name == "String":
                    return cls("")
                if class_name == "Nil":
                    return Builtins.nil
                if class_name == "Object":
                    return ObjectInstance()
                return cls()
            
            if class_name == "Block":
                empty_block = Block(arity=0, parameters=[], assigns=[])
                return BlockInstance(empty_block, frame)
            
            # User defined classes
            for cl in self.current_program.classes:
                if class_name == cl.name:
                    return ClassInstance(cl)

        if selector == "from:" and len(args) == 1:
            return self.dispatch_from(class_name, args[0])

        if selector == "read" and class_name == "String":
            line = self.input_io.readline()
            if line.endswith("\n"):
                line = line[:-1]
            return Builtins.SOLString(line)
        
    def dispatch_from(self, class_name, obj):
        if class_name == "Integer":
            if not hasattr(obj, "value") or not isinstance(obj.value, int):
                raise InterpreterError(ErrorCode.INT_INVALID_ARG, "from: requires Integer-compatible object")
            return Builtins.SOLInteger(obj.value)
        
        if class_name == "String":
            if not hasattr(obj, "value") or not isinstance(obj.value, str):
                raise InterpreterError(ErrorCode.INT_INVALID_ARG, "from: requires String-compatible object")
            return Builtins.SOLString(obj.value)
        
        if class_name == "Nil":
            return Builtins.nil
        
        if class_name == "Object":
            new_inst = ObjectInstance()
            if isinstance(obj, (ClassInstance, ObjectInstance)):
                new_inst.attributes = dict(obj.attributes)
            return new_inst
        
        for cl in self.current_program.classes:
            if class_name == cl.name:
                new_inst = ClassInstance(cl)
                if isinstance(obj, ClassInstance):
                    new_inst.attributes = dict(obj.attributes)
                if hasattr(obj, "value"):
                    new_inst.value = obj.value
                return new_inst
        
        raise InterpreterError(ErrorCode.SEM_UNDEF, f"Unknown class: {class_name}")
        
    def dispatch_block(self, receiver, selector, args, current_class):
        if selector == "isBlock":
            return Builtins.SOLTrue()
        
        if selector == "whileTrue:" and len(args) == 1:
            result = Builtins.nil
            while True:
                cond = self.execute_block(receiver, current_class, [])
                if not isinstance(cond, Builtins.SOLTrue):
                    break
                result = self.execute_block(args[0], current_class, [])
            return result
        
        if selector == "value":
            return self.execute_block(receiver, current_class, [])
        
        if selector == "value:" and len(args) == 1:
            return self.execute_block(receiver, current_class, args)
        
        if selector == "value:value:" and len(args) == 2:
            return self.execute_block(receiver, current_class, args)
        
        return Builtins.nil
        
    def dispatch_instance(self, receiver, selector, args, current_class, is_super):
        if is_super:
            method = receiver.find_method_from_parent(selector, self.current_program.classes, current_class)
        else:
            method = receiver.find_method(selector, self.current_program.classes)

        if method is not None:
            return self.execute_method(method, receiver, args)
        
        base_name = receiver.get_base(self.current_program.classes)
        builtin_class = self.builtin_classes[base_name]
        result = self.dispatch_builtin(builtin_class(), selector, args, current_class)
        if result is not None:
            return result
        
        return self.attribute_fallback(receiver, selector, args)
    
    def dispatch_builtin(self, receiver, selector, args, current_class):
        # Boolean ifTrue ifFalse
        if isinstance(receiver, (Builtins.SOLTrue, Builtins.SOLFalse)):
            if selector == "ifTrue:ifFalse:" and len(args) == 2:
                if isinstance(receiver, Builtins.SOLTrue):
                    return self.execute_block(args[0], current_class, [])
                return self.execute_block(args[1], current_class, [])
    
        # Boolean and: with Block on left side
        if selector == "and:" and len(args) == 1:
            if isinstance(receiver, Builtins.SOLFalse):
                return Builtins.SOLFalse()
            if isinstance(args[0], BlockInstance):
                return self.execute_block(args[0], current_class, [])
            
        # Boolean or: with Block on left side
        if selector == "or:" and len(args) == 1:
            if isinstance(receiver, Builtins.SOLTrue):
                return Builtins.SOLTrue()
            if isinstance(args[0], BlockInstance):
                return self.execute_block(args[0], current_class, [])

        # Integer timesRepeat:
        if isinstance(receiver, Builtins.SOLInteger):
            if selector == "timesRepeat:" and len(args) == 1:
                result = Builtins.nil
                for i in range(1, receiver.value + 1):
                    result = self.execute_block(args[0], current_class, [Builtins.SOLInteger(i)])
                return result
            
        if selector == "isBlock":
            return Builtins.SOLFalse()

        method_name = selector.replace(":", "_")
        if selector == "print":
            method_name = "print_"
        
        if selector == "not":
            method_name = "not_"

        method = getattr(receiver, method_name, None)
        if method is not None:
            return method(*args)

        return None
    
    def attribute_fallback(self, receiver, selector, args):
        if len(args) == 0:
            val = receiver.attributes.get(selector)
            if val is None:
                raise InterpreterError(ErrorCode.INT_DNU, f"No method or attribute '{selector}'!")
            return val

        if len(args) == 1:
            attr_name = selector.rstrip(":")
            collision = receiver.find_method(attr_name, self.current_program.classes)
            if collision is not None:
                raise InterpreterError(ErrorCode.INT_INST_ATTR, f"Attribute '{attr_name}' collides with method!")
            base_name = receiver.get_base(self.current_program.classes)
            builtin_class = self.builtin_classes[base_name]

            if getattr(builtin_class(), attr_name, None) is not None:
                raise InterpreterError(ErrorCode.INT_INST_ATTR, f"Attribute '{attr_name}' collides with builtin method!")
                
            receiver.attributes[attr_name] = args[0]
            return receiver
        
        raise InterpreterError(ErrorCode.INT_DNU, f"No method '{selector}!'")
        
    def execute_method(self, method, current_class, args):
        if args is None:
            args = []
        frame = {}
        frame["self"] = current_class
        frame["super"] = current_class
        
        result = Builtins.nil

        method_block = BlockInstance(method.block, frame)

        result = self.execute_block(method_block, current_class, args)
        return result

    def execute_block(self, block_instance, current_class, args):
        frame = dict(block_instance.parent_frame)
        
        params = block_instance.block.parameters
        if len(params) != len(args):
            raise InterpreterError(ErrorCode.INT_DNU, f"Block arity mismatch!")
        
        param_names = {p.name for p in params}
        for param, arg in zip(params, args):
            frame[param.name] = arg
        
        result = Builtins.nil
        for stmt in block_instance.block.assigns:
            if stmt.target.name in param_names:
                raise InterpreterError(ErrorCode.SEM_COLLISION, f"Assignment to parameter {stmt.target.name}")
            result = self.eval_expr(stmt.expr, frame, current_class)
            frame[stmt.target.name] = result
        return result

class ClassInstance:
    def __init__(self, cl):
        self.cl = cl
        self.cl_name = cl.name
        self.attributes = {}

    def find_method(self, selector, all_classes):
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
    
    def find_method_from_parent(self, selector, all_classes, from_class):
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
    
    def get_base(self, all_classes):
        current = self.cl
        base_names = {"Object", "Integer", "String", "Nil", "True", "False", "Block"}

        while current is not None:
            if current.parent in base_names:
                return current.parent
            
            parent_name = current.parent
            current = None

            for cl in all_classes:
                if cl.name == parent_name:
                    current = cl
                    break
        
        return "Object"
    
class BlockInstance:
    def __init__(self, block, parent_frame):
        self.block = block
        self.parent_frame = parent_frame
    
class ObjectInstance:
    def __init__(self) -> None:
        self.cl_name = "Object"
        self.attributes: dict = {}

    def find_method(self, selector: str, all_classes: list) -> None:
        return None

    def find_method_from_parent(self, selector: str, all_classes: list, from_class: object) -> None:
        return None

    def get_base(self, all_classes: list) -> str:
        return "Object"

    def __repr__(self) -> str:
        return "instance of Object"