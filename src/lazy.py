import inspect
import ast
import logging
from typing import Callable, Optional, Any
from src.base import remove_code_blocks
from src.base import Bot
from src.anthropic_bots import AnthropicBot

# Set up logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# Create a filter to exclude HTTP-related logs
class NoHTTPFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return 'response' not in record.name.lower()


# Apply the filter to our logger
logger.addFilter(NoHTTPFilter())


def lazy(prompt: Optional[str] = None, bot: Optional[Bot] = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        nonlocal bot
        nonlocal prompt
        if bot is None:
            bot = AnthropicBot(name='Claude')
        if prompt is None:
            prompt = ''

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not wrapper.initialized:
                function_name: str = func.__name__
                logger.debug(f"Initializing lazy function: {function_name}")
                instructions: str = (
                    "Please fill out the following function definition according to the following "
                    "requirements. Respond only with the code in a single code block. Include all "
                    "import statements inside the function definition."
                )
                complete_prompt: str = (
                    f"{instructions}\n\n{prompt}\n\n{function_name}{str(inspect.signature(func))}"
                )
                response: str = bot.respond(complete_prompt)
                function_code, _ = remove_code_blocks(response)
                function_code = function_code[0]
                logger.debug(f"Generated function code:\n{function_code}")

                # Write the function code to the source file
                source_file: str = inspect.getfile(func)
                logger.debug(f"Source file: {source_file}")
                with open(source_file, 'r') as file:
                    source_lines: str = file.read()
                logger.debug(f"Original source file content:\n{source_lines}")

                # Parse the original source code into an AST
                source_tree: ast.AST = ast.parse(source_lines)

                class FunctionReplacer(ast.NodeTransformer):
                    def __init__(self, function_name: str, new_code: str):
                        self.function_name = function_name
                        self.new_code = new_code

                    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
                        if node.name == self.function_name:
                            logger.debug(f"Replacing function: {self.function_name}")
                            new_node: ast.AST = ast.parse(self.new_code).body[0]
                            return new_node
                        return node

                # Replace the function
                function_replacer = FunctionReplacer(function_name, function_code)
                new_tree: ast.AST = function_replacer.visit(source_tree)
                ast.fix_missing_locations(new_tree)

                # Convert the modified AST back to source code
                new_source_lines: str = ast.unparse(new_tree)
                logger.debug(f"New source file content:\n{new_source_lines}")

                # Write the updated lines back to the source file
                with open(source_file, 'w') as file:
                    file.write(new_source_lines)
                logger.debug("Updated source file written")

                # Execute the newly written function code in the global scope
                exec(function_code, globals(), globals())

                # Mark the function as initialized
                wrapper.initialized = True
                logger.debug(f"Lazy function {function_name} initialized")

            return globals()[func.__name__](*args, **kwargs)

        wrapper.initialized = False
        return wrapper

    return decorator