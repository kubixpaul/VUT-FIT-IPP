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
        
        frame = {}

        for stmt in run_method.block.assigns:
            frame[stmt.target.name] = self.eval_expr(stmt.expr, frame)
            

        for name in frame:
            print(f"{name} = {frame[name]}")

        # print(self.current_program)

        """"
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
            return expr.literal.value

        # --- VAR ---
        if expr.var is not None:
            name = expr.var.name
            if name not in frame:
                ErrorCode.fire(ErrorCode.SEM_UNDEF, "Missing definition of variable!")
            return frame[name]
        
        # -- BLOCK --
        if expr.block is not None:
            return BlockInstance(expr.block, frame)

        # --- SEND ---
        if expr.send is not None:
            send = expr.send
            receiver = self.eval_expr(send.receiver, frame)

            # --- new ---
            if send.selector == "new":
                class_names = {cls.name for cls in self.current_program.classes}

                if receiver not in class_names:
                    ErrorCode.fire(ErrorCode.SEM_UNDEF, "Missing definition of class!")

                return Instance(receiver)
            return send.selector

class Instance:
    def __init__(self, cls_name):
        self.cls_name = cls_name
        self.attributes = {}

    def __repr__(self):
        return f"instance of {self.cls_name}"
    
class BlockInstance:
    def __init__(self, block, parent_frame):
        self.block = block
        self.parent_frame = parent_frame

    def __repr__(self):
        return "<block>"
    
