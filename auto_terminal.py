import bots
import os
from bots import Engines
import textwrap
import subprocess
import os
import ast
import astor

class IndentVisitor(ast.NodeTransformer):
    def __init__(self, indent='    '):
        self.indent = indent
        self.level = 0
    
    def visit(self, node):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.If, ast.For, ast.While, ast.With)):
            self.level += 1
            node = self.generic_visit(node)
            self.level -= 1
        else:
            node = self.generic_visit(node)
        if hasattr(node, 'body') and isinstance(node.body, list):
            node.body = [ast.Expr(ast.Str(self.indent * self.level))] + node.body
        return node

def indent_code(code, indent='    '):
    tree = ast.parse(code)
    IndentVisitor(indent).visit(tree)
    return astor.to_source(tree)

def execute_python_code(code, timeout=300):
    # Indent the code using AST
    indented_code = indent_code(code)
    # Wrap the indented code in a function
    wrapped_code = f"""
import sys
import traceback
def main():
{indented_code}
if __name__ == '__main__':
    try:
        main()
    except Exception as error_error:
        print(f"An error occurred: {{str(error_error)}}", file=sys.stderr)
        print("Local variables at the time of the error:", file=sys.stderr)
        tb = sys.exc_info()[2]
        while tb:
            frame = tb.tb_frame
            tb = tb.tb_next
            print(f"Frame {{frame.f_code.co_name}} in
{{frame.f_code.co_filename}}:{{frame.f_lineno}}", file=sys.stderr)
            local_vars = dict(frame.f_locals)
            for key, value in local_vars.items():
                if not key.startswith('__') and key not in ['sys', 'traceback', 'error_error',
'main', 'tb', 'frame', 'Frame']:
                    print(f"    {{key}} = {{value}}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
"""

    # Create a temporary file in the current working directory
    temp_file_name = os.path.join(os.getcwd(), 'temp_script.py')
    
    with open(temp_file_name, 'w', encoding='utf-8') as temp_file:
        temp_file.write(code)
        temp_file.flush()
    
    try:
        # Execute the Python code in a separate process
        process = subprocess.Popen(['python', temp_file_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        try:
            # Wait for the process to complete with a timeout
            stdout, stderr = process.communicate(timeout=timeout)
            return stdout + stderr
        except subprocess.TimeoutExpired:
            # Terminate the process if it exceeds the timeout
            process.terminate()
            return f"Error: Code execution timed out after {timeout} seconds."
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_file_name):
            os.remove(temp_file_name)

def pretty(string, name=None, width=100, indent=4):
    # Prepare the initial line
    if name is None:
        prefix = ""
    else:
        prefix = f"{name}: "
    
    # Split the input string into lines
    lines = string.split('\n')
    
    # Process each line
    formatted_lines = []
    for i, line in enumerate(lines):
        # For the first line, include the prefix
        if i == 0:
            initial_line = prefix + line
            wrapped = textwrap.wrap(initial_line, width=width, subsequent_indent=' ' * indent)
        else:
            # For subsequent lines, apply indentation to all parts
            wrapped = textwrap.wrap(line, width=width, initial_indent=' ' * indent, subsequent_indent=' ' * indent)
        formatted_lines.extend(wrapped)
    
    # Print the formatted text
    print('\n'.join(formatted_lines))
    print("\n---\n")

def main():
    B1 = bots.AnthropicBot(name='Claude', model_engine=Engines.CLAUDE35)
    B1 = B1.load("Claude@2024.07.12-10.23.14.bot")
    pretty(B1.conversation.to_string())
    turn = 'user'
    auto = 0

    while(True):
        initial_message = 'No code to execute'
        output = initial_message
    
        if(turn=='assistant'):
            if auto > 1:
                auto = auto - 1
                output = f'Auto-mode enabled for {auto} more messages\n\n'
            else:
                turn = 'user'
            response = B1.respond(msg)
            pretty(response, B1.name)
            code_blocks, labels = bots.remove_code_blocks(response)
            if code_blocks:
                for code, label in zip(code_blocks, labels):

                    if label.lower() == "epowershell":
                        try:
                            if output == initial_message: output = 'Executed Code Result:\n'
                            result = subprocess.run(["powershell", "-Command", code], capture_output=True, text=True, timeout=30)
                            output += result.stdout + result.stderr
                        except subprocess.TimeoutExpired:
                            output += "Error: Command execution timed out after 30 seconds."
                        except Exception as e:
                            output += f"Error: {str(e)}"
        
                    elif label.lower() == 'epython':
                        try:
                            if output == initial_message: output = 'Executed Code Result:\n'
                            result = execute_python_code(code)
                            output += result + '\n'
                        except Exception as e:
                            output += f"Error: {str(e)}"
                            
                    output = output + '\n---\n'

        msg = 'System:\n' + output + "\n---\n"
        pretty(output, 'System')
        
        if(turn=='user'):
            uinput = input("You: ")
            if uinput.lower().startswith('/exit'):
                exit()
            elif uinput.lower().startswith('/save'):
                filename = B1.save()
                pretty(f"Conversation saved to {filename}", 'System')
                turn = 'user'
            elif uinput.lower().startswith('/load'):
                filename = input("Filename:")
                if os.path.exists(filename):
                    B1 = B1.load(filename)
                    pretty(f"Conversation loaded from {filename}", 'System')
                else:
                    pretty(f"File {filename} not found.", 'System')
                turn = 'user'
            elif uinput.lower().startswith('/auto'):
                auto = int(input("Number of automatic cycles:"))
                turn = 'user'
            else:   
                msg = msg + "\nBen's Reply:\n" + uinput 
                pretty('')
                turn = 'assistant'
    
if __name__ == '__main__':
    main()
