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
from interpreter.input_model import Program
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
        logger.info("Executing program")

        self.builtin_classes = {
            "Object": Builtins.SOLObject,
            "Integer": Builtins.SOLInteger,
            "String": Builtins.SOLString,
            "Nil": Builtins.SOLNil,
            "True": Builtins.SOLTrue,
            "False": Builtins.SOLFalse,
            "Block": Builtins.SOLBlock,
        }

        main_class = None
        for cl in self.current_program.classes:
            if cl.name == "Main":
                main_class = cl
                break
        if main_class is None:
            ErrorCode.fire(ErrorCode.SEM_MAIN, "Missing Main class in program!")
        run_method = None
        for method in main_class.methods:
            if method.selector == "run":
                run_method = method
                break
        if run_method is None:
            ErrorCode.fire(ErrorCode.SEM_MAIN, "Missing run method in Main!")

        #self.execute_method(run_method)

        print(self.current_program)

        """
        for stmt in run_method.block.assigns:
            print(f"Assign order={stmt.order}")
            print(f"  target = {stmt.target.name}")

            expr = stmt.expr
            print("  expr:")

            if expr.literal is not None:
                print(f"    literal: class={expr.literal.class_id}, value={expr.literal.value}")

            elif expr.var is not None:
                print(f"    var: {expr.var.name}")

            elif expr.block is not None:
                print(f"    block: arity={expr.block.arity}")
                print(f"      parameters: {[p.name for p in expr.block.parameters]}")
                print(f"      assigns: {len(expr.block.assigns)} inner assigns")

            elif expr.send is not None:
                send = expr.send
                print(f"    send: selector={send.selector}")
                print("      receiver:")
                if send.receiver.var:
                    print(f"        var: {send.receiver.var.name}")
                elif send.receiver.literal:
                    print(f"        literal: {send.receiver.literal.value}")
                elif send.receiver.send:
                    print(f"        nested send: {send.receiver.send.selector}")

                print("      args:")
                for arg in send.args:
                    print(f"        arg order={arg.order}:")
                    if arg.expr.literal:
                        print(f"          literal: {arg.expr.literal.value}")
                    elif arg.expr.var:
                        print(f"          var: {arg.expr.var.name}")
                    elif arg.expr.send:
                        print(f"          send: {arg.expr.send.selector}")

            print()
        """

    def eval_expr(self, expr, frame):
        # --- LITERAL ---
        if expr.literal is not None:
            lit = expr.literal

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

        # --- VAR ---
        if expr.var is not None:
            name = expr.var.name
            if name not in frame:
                ErrorCode.fire(ErrorCode.SEM_UNDEF, "Missing definition of variable!")
            return frame[name]
        
        # -- BLOCK --
        if expr.block is not None:
            return BlockInstance(expr.block)

        # --- SEND ---
        if expr.send is not None:
            send = expr.send
            receiver = self.eval_expr(send.receiver, frame)

            args = []
            for arg in send.args:
                args.append(self.eval_expr(arg.expr, frame))

            # --- new ---
            if send.selector == "new":
                if receiver in self.builtin_classes:
                    cls = self.builtin_classes[receiver]

                    if receiver == "Integer":
                        return cls(0)
                    if receiver == "String":
                        return cls("")
                    if receiver == "Nil":
                        return Builtins.nil

                    return cls()

                for cl in self.current_program.classes:
                    if receiver == cl.name:
                        return ClassInstance(cl)
                ErrorCode.fire(ErrorCode.SEM_UNDEF, "Missing definition of class!")

            if isinstance(receiver, ClassInstance):
                method = receiver.find_method(send.selector, self.current_program.classes)
                if method is None:
                    base_name = receiver.get_base(self.current_program.classes)
                    builtin_class = self.builtin_classes[base_name]
                    method_name = send.selector.replace(":", "_")
                    if method_name == "print":
                        method_name = "print_"

                    method = getattr(builtin_class(), method_name, None)
                    if method is not None:
                        return method(*args)

                    if len(args) == 0:
                        val = receiver.attributes.get(send.selector)
                        if val is None:
                            ErrorCode.fire(ErrorCode.INT_DNU, f"No method or attribute with name '{send.selector}' found!")
                        return val
                    elif len(args) == 1:
                        attr_name = send.selector.rstrip(":")
                        collision = receiver.find_method(attr_name, self.current_program.classes)
                        if collision is not None:
                            ErrorCode.fire(ErrorCode.INT_DNU, f"Attribute '{attr_name}' collides with method")
                        
                        base_name = receiver.get_base(self.current_program.classes)
                        builtin_class = self.builtin_classes[base_name]
                        if getattr(builtin_class(), attr_name, None) is not None:
                            ErrorCode.fire(ErrorCode.INT_INST_ATTR, f"Attribute '{attr_name}' collides with builtin method")
                        receiver.attributes[attr_name] = args[0]
                        return receiver
                    else:
                        ErrorCode.fire(ErrorCode.INT_DNU, "Missing definition of method!")
                return self.execute_method(method)
            return send.selector
        
    def execute_method(self, method):
        result = None
        frame = {}
        for stmt in method.block.assigns:
            result = self.eval_expr(stmt.expr, frame)
            frame[stmt.target.name] = result

        #for name in frame:
        #    print(f"{name} = {frame[name]}")
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
    
    def __repr__(self):
        return f"instance of {self.cl_name}"
    
class BlockInstance:
    def __init__(self, block):
        self.block = block

    def __repr__(self):
        return "<block>"
    
