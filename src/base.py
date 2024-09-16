import os
import sys
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Union, Type, Dict, Any, List, Callable, Tuple
import datetime as DT
import json
import re
import ast
from types import ModuleType
import threading
import inspect
import hashlib

# TODO be consistent about what _function_name() means (the underscore)

def remove_code_blocks(text: str) ->Tuple[List[str], List[str]]:
    pattern = '```(\\w*)\\s*([\\s\\S]*?)```'
    matches = re.findall(pattern, text)
    code_blocks = [match[1].strip() for match in matches]
    labels = [match[0].strip() for match in matches]
    text = re.sub(pattern, '', text)
    return code_blocks, labels


def load(filepath: str) ->'Bot':
    return Bot.load(filepath)


def formatted_datetime() ->str:
    now = DT.datetime.now()
    return now.strftime('%Y-%m-%d_%H-%M-%S')


class Engines(str, Enum):
    """Enum class representing different AI model engines."""
    GPT4 = 'gpt-4'
    GPT4Turbo = 'gpt-4-turbo'
    GPT35 = 'gpt-3.5-turbo'
    CLAUDE3OPUS = 'claude-3-opus-20240229'
    CLAUDE3SONNET = 'claude-3-sonnet-20240229'
    CLAUDE35 = 'claude-3-5-sonnet-20240620'

    @staticmethod
    def get(name):
        """Retrieve an Engines enum member by its value."""
        for engine in Engines:
            if engine.value == name:
                return engine
        return None

    @staticmethod
    def get_bot_class(model_engine: 'Engines') -> Type['Bot']:
        """Returns the bot class based on the model engine."""
        if model_engine in [Engines.GPT4, Engines.GPT35, Engines.GPT4Turbo]:
            from src.openai_bots import GPTBot
            return GPTBot
        elif model_engine in [Engines.CLAUDE3OPUS, Engines.CLAUDE3SONNET, Engines.CLAUDE35]:
            from src.anthropic_bots import AnthropicBot
            return AnthropicBot
        else:
            raise ValueError(f'Unsupported model engine: {model_engine}')


class ConversationNode:

    def __init__(self, content, role, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.role = role
        self.content = content
        self.replies: list[ConversationNode] = []
        self.parent: ConversationNode = None

    @staticmethod
    def create_empty(cls=None):
        if cls:
            return cls(role="empty", content='')
        return ConversationNode(role='empty', content='')

    def is_empty(self):
        return self.role == 'empty' and self.content == ''

    def add_reply(self, **kwargs):
        if self.is_empty():
            self.__init__(**kwargs)
            return self
        else:
            reply = type(self)(**kwargs)
            reply.parent = self
            self.replies.append(reply)
            return reply

    def find_root(self):
        """ Navigate to the root of the conversation tree. """
        current = self
        while current.parent is not None:
            current = current.parent
        return current

    def root_dict(self):
        """ Convert the conversation tree starting from the root to a dictionary. """
        root = self.find_root()
        return root._to_dict_recursive()
    
    def _to_dict_recursive(self):
        """ Recursively convert this node and its replies to a dictionary. """
        # Gather all relevant attributes except 'parent'
        result = self._to_dict_self()
        if self.replies:
            result['replies'] = [reply._to_dict_recursive() for reply in self.replies]
        return result

    def _to_dict_self(self):
        """ Convert this node to a dictionary, omitting replies, parent, callables, and private attributes."""
        # Exclude callables, double underscore attributes, and specific attributes that could lead to recursive structures
        return {
            k: getattr(self, k) for k in dir(self)
            if not k.startswith('_') and
               k not in {'parent', 'replies'} and
               not callable(getattr(self, k))
        }
    
    def build_messages(self):
        node = self
        if node.is_empty():
            return []
        conversation_dict = []
        while node:
            entry = {'role': node.role, 'content': node.content}
            conversation_dict = [entry] + conversation_dict
            node = node.parent
        return conversation_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) ->'ConversationNode':
        node = cls(**{k: v for k, v in data.items() if k != 'replies'})
        for reply_data in data.get('replies', []):
            reply_node = cls.from_dict(reply_data)
            reply_node.parent = node
            node.replies.append(reply_node)
        return node
    
    def node_count(self) -> int:
        """ Recursively count the total number of nodes in the conversation, starting from the root. """
        # First, navigate to the root of the conversation tree
        root = self.find_root()
    
        # Now count all nodes starting from the root
        def count_recursive(current_node):
            count = 1  # Count the current node
            for reply in current_node.replies:
                count += count_recursive(reply)  # Recursively count all replies
            return count
    
        return count_recursive(root)


class ToolHandler(ABC):

    def __init__(self):
        self.tools: List[Dict[str, Any]] = []
        self.function_map: Dict[str, Callable] = {}
        self.requests: List[Dict[str, Any]] = []
        self.results: List[Dict[str, Any]] = []

    @abstractmethod
    def generate_tool_schema(self, func: Callable) ->Dict[str, Any]:
        """
            Generate tool schema from callable function
            Return schema as dictionary
        """
        pass

    @abstractmethod
    def generate_request_schema(self, response: Any) ->List[Dict[str, Any]]:
        """
            Generate request schema from response
            Return list of schemas (multiple requests may be in one message)
        """
        pass

    @abstractmethod
    def tool_name_and_input(self, request_schema) ->Tuple[str, Dict[str, Any]]:
        """ 
            Extract tool name and input from request
            Return (tool name, kwargs) 
        """
        pass

    @abstractmethod
    def generate_response_schema(self, request, tool_output_kwargs) ->Dict[
        str, Any]:
        """
            Generate response schema from request and tool output
            Return schema
        """
        pass

    def handle_response(self, response) ->Tuple[List[Dict[str, str]], List[
        Dict[str, str]]]:
        """Runs tools and returns (request schema, result schema) from input response"""
        self.clear()
        requests = self.generate_request_schema(response)
        if requests:
            for request_schema in requests:
                tool_name, input_kwargs = self.tool_name_and_input(request_schema)
                output_kwargs = self.function_map[tool_name](**input_kwargs)
                response_schema = self.generate_response_schema(request_schema,
                    output_kwargs)
                self.requests.append(request_schema)
                self.results.append(response_schema)
        return self.requests, self.results

    def add_tool(self, func: Callable) ->None:
        schema = self.generate_tool_schema(func)
        if schema:
            self.tools.append(schema)
            self.function_map[func.__name__] = func

    def add_tools_from_file(self, filepath: str) ->None:
        functions = self.extract_functions(filepath)
        for func in functions:
            self.add_tool(func)

    def extract_functions(self, file_path: str) ->List[Callable]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File '{file_path}' not found.")
        abs_file_path = os.path.abspath(file_path)
        file_dir = os.path.dirname(abs_file_path)
        sys.path.insert(0, file_dir)
        try:
            with open(abs_file_path, 'r') as file:
                content = file.read()
            module = ast.parse(content)
            imports = []
            functions = []
            for node in module.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    imports.append(node)
                elif isinstance(node, ast.FunctionDef):
                    functions.append(node)
            new_module = ast.Module(body=imports + functions, type_ignores=[])
            compiled = compile(new_module, filename=abs_file_path, mode='exec')
            namespace = ModuleType('dynamic_module')
            namespace.__file__ = abs_file_path
            exec(compiled, namespace.__dict__)
            extracted_functions = []
            for func in functions:
                if (func.name in namespace.__dict__ and not func.name.
                    startswith('_')):
                    extracted_functions.append(namespace.__dict__[func.name])
            return extracted_functions
        finally:
            sys.path.pop(0)

    def get_tools_json(self) ->str:
        """Return a JSON string representation of all tools."""
        return json.dumps(self.tools, indent=1)

    def clear(self) ->None:
        """Clear the stored results and requests."""
        self.results = []
        self.requests = []

    def add_request(self, request: Dict[str, Any]) ->None:
        """Add a request to the stored requests."""
        self.requests.append(request)

    def add_result(self, result: Dict[str, Any]) ->None:
        """Add a result to the stored results."""
        self.results.append(result)

    def get_results(self) ->List[Dict[str, Any]]:
        """Get all stored results."""
        return self.results

    def get_requests(self) ->List[Dict[str, Any]]:
        """Get all stored requests"""
        return self.requests

    def to_dict(self) ->Dict[str, Any]:
        return {'class': self.__class__.__name__, 'tools': self.tools,
            'function_map': {k: {'name': v.__name__, 'code': inspect.
            getsource(v), 'file_path': inspect.getfile(v), 'file_hash':
            self._get_file_hash(inspect.getfile(v))} for k, v in self.
            function_map.items()}, 'requests': self.requests, 'results':
            self.results}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) ->'ToolHandler':
        handler = cls()
        handler.tools = data['tools']
        handler.results = data['results']
        handler.requests = data['requests']
        for _, func_data in data['function_map'].items():
            if os.path.exists(func_data['file_path']):
                current_hash = handler._get_file_hash(func_data['file_path'])
                if current_hash == func_data['file_hash']:
                    handler.add_tools_from_file(func_data['file_path'])
                    continue
            exec(func_data['code'], globals())
            func = globals()[func_data['name']]
            handler.add_tool(func)
        return handler

    def _get_file_hash(self, file_path: str) ->str:
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()


class Mailbox(ABC):

    def __init__(self):
        self.log_file = 'data\\mailbox_log.txt'

    def log_message(self, message: str, direction: str) ->None:
        timestamp = formatted_datetime()
        log_entry = f'[{timestamp}] {direction.upper()}:\n{message}\n\n'
        with open(self.log_file, 'a', encoding='utf-8') as file:
            file.write(log_entry)

    def send_message(self, bot: 'Bot') -> tuple[str, str, Dict[str, Any]]:
        model = bot.model_engine
        max_tokens = bot.max_tokens
        temperature = bot.temperature
        self._log_outgoing(bot.conversation, model.value, max_tokens, temperature)
        try:
            response = self._send_message_implementation(bot)
            processed_response = self._process_response(response, bot)
        except Exception as e:
            raise e
        self._log_incoming(processed_response)
        return processed_response

    @abstractmethod
    def _send_message_implementation(self, bot: 'Bot') ->Dict[str, Any]:
        """
        Implement the actual message sending logic for a specific AI service.

        This method should handle the API call to the AI service and return the raw response.
        It *may* also handle any tool results, depending on the api.

        Parameters:
        - bot: a reference to a "Bot" or subclass

        Returns:
        Dict[str, Any]: The raw response from the AI service as a Dict

        Raises:
        Exception: If there's an error in sending the message or receiving the response.
        """
        pass

    @abstractmethod
    def _process_response(self, response: Dict[str, Any], bot: 'Bot' = None
        ) -> Tuple[str, str, Dict[str, Any]]:
        """
        Process the raw response from the AI service into a standardized format.

        This method should extract the relevant information from the AI's response
        and return it in a consistent format across different AI services.

        Parameters:
        - response (Dict[str, Any]): The raw response from the AI service.
        - bot (Bot): A Bot object. This is required in the case that, in processing
            a response, a new message must be sent (such as in the case of openai 
            tool processing)

        Returns:
        tuple[str, str, Dict[str, Any]]: A tuple containing:
            - The response text (str)
            - The role of the responder (str, e.g., "assistant")
            - Additional metadata or parsed information (Dict[str, Any])
                - This additional data will be passed to ConversationNode's kwargs 
                argument directly
                - By default, Conversation Node saves each kwarg as an attribute
        
        Note:
        The exact structure of the returned tuple may vary depending on the specific 
        requirements of your application, but it should be consistent across all 
        implementations of this method.
        """
        pass

    def _log_outgoing(self, conversation: ConversationNode, model: Engines,
        max_tokens, temperature):
        log_message = {'date': formatted_datetime(), 'messages':
            conversation.build_messages(), 'max_tokens': max_tokens,
            'temperature': temperature, 'model': model}
        self._log_message(json.dumps(log_message, indent=1), 'OUTGOING')

    def _log_incoming(self, processed_response):
        log_message = {'date': formatted_datetime(), 'response':
            processed_response}
        self._log_message(json.dumps(log_message, indent=1), 'INCOMING')

    def _log_message(self, message: str, direction: str) ->None:
        timestamp = formatted_datetime()
        log_entry = f'[{timestamp}] {direction.upper()}:\n{message}\n\n'
        with open(self.log_file, 'a', encoding='utf-8') as file:
            file.write(log_entry)

    def batch_send(self, conversations, model, max_tokens, temperature,
        api_key, system_message=None):
        raise NotImplemented
        threads = []
        results = [None] * len(conversations)

        def send_thread(index, conv):
            result = self.send_message(self)
            results[index] = result
        for i, conversation in enumerate(conversations):
            thread = threading.Thread(target=send_thread, args=(i,
                conversation))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        return results


class Bot(ABC):

    def __init__(self, api_key: Optional[str], model_engine: Engines,
        max_tokens: int, temperature: float, name: str, role: str,
        role_description: str, conversation: Optional[ConversationNode]=
        ConversationNode.create_empty(), tool_handler: Optional[ToolHandler
        ]=None, mailbox: Optional[Mailbox]=None):
        self.api_key = api_key
        self.name = name
        self.model_engine = model_engine
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.role = role
        self.role_description = role_description
        self.conversation: ConversationNode = conversation
        self.system_message = ''
        self.tool_handler = tool_handler
        self.mailbox = mailbox
        if isinstance(self.model_engine, str):
            self.model_engine = Engines.get(self.model_engine)

    def respond(self, content: str, role: str='user', tool_auto=False) ->str:
        """
        Sends 'content' to the Bot and returns the text response
        If tool_auto is True, loops until the bot does not use a tool
        """
        if tool_auto:
            reply, self.conversation = self._respond_auto(content, self.conversation, role)
        else:
            reply, self.conversation = self._cvsn_respond(text=content,role=role)
        return reply

    def _cvsn_respond(self, text: Optional[str]=None, role: str='user') -> Tuple[str, ConversationNode]:    

        if self.conversation is None and text is None:
            # ya f'ed up!
            raise ValueError('Invalid: both text and conversation are None')

        # Handle new conversation items
        if text is not None:
            self.conversation = self.conversation.add_reply(content=text, role=role)

        # Now that the conversation is settled, send the message
        try:
            response_text, response_role, extra_data = self.mailbox.send_message(self)
            self.conversation = self.conversation.add_reply(content=response_text, role=response_role, **extra_data)
            return response_text, self.conversation
        except Exception as e:
            raise e


    def add_tool(self, func: Callable):
        self.tool_handler.add_tool(func)

    def add_tools(self, filepath):
        self.tool_path = filepath
        self.tool_handler.add_tools_from_file(filepath)

    def _respond_auto(self, content: str, conversation: ConversationNode,
        role: str) ->str:
        """Automatically handles tool use and responses for Anthropic models"""
        response = self.respond(content, role, tool_auto=False)
        total_reply = response
        max_tool_prompts = 8
        tool_prompt_counter = 1
        while tool_prompt_counter < max_tool_prompts:
            extra_data = getattr(self.conversation, 'attributes', {})
            print('\n\n'+response)
            print('\n\n'+str(extra_data))
            print(f'\n\n{max_tool_prompts-tool_prompt_counter} toolings remaining')
            if extra_data.get('requests'):
                follow_up = f'(auto for {max_tool_prompts-tool_prompt_counter} more tool calls max)'
                response = self.respond(follow_up, role)
                total_reply += '\n\n ...working... \n\n' + response
                tool_prompt_counter += 1
            else:
                break
        return total_reply, self.conversation

    def set_system_message(self, message: str) ->None:
        self.system_message = message

    @classmethod
    def load(cls, filepath: str, api_key=None) ->'Bot':
        with open(filepath, 'r') as file:
            data = json.load(file)
        bot_class = Engines.get_bot_class(Engines(data['model_engine']))
        init_params = inspect.signature(bot_class.__init__).parameters
        constructor_args = {k: v for k, v in data.items() if k in init_params}
        if 'tool_handler' in constructor_args:
            tool_handler_class = constructor_args['tool_handler']['class']
            constructor_args['tool_handler'] = tool_handler_class.from_dict(
                constructor_args['tool_handler'])
        bot = bot_class(**constructor_args)
        bot.api_key = api_key if api_key is not None else None
        for key, value in data.items():
            if key not in constructor_args and key != 'conversation':
                setattr(bot, key, value)
        if 'conversation' in data and data['conversation']:
            bot.conversation = ConversationNode.from_dict(data['conversation'])
        return bot

    def save(self, filename: Optional[str]=None) ->str:
        now = formatted_datetime()
        if filename is None:
            filename = f'{self.name}@{now}.bot'
        data = {key: value for key, value in self.__dict__.items() if not
            key.startswith('_')}
        data.pop('api_key')
        data.pop('mailbox')
        data['bot_class'] = self.__class__.__name__
        data['model_engine'] = self.model_engine.value
        data['conversation'] = self.conversation.root_dict()
        if 'tool_handler' in data and data:
            data['tool_handler'] = data['tool_handler'].to_dict()
        for key, value in data.items():
            if not isinstance(value, (str, int, float, bool, list, dict,
                type(None))):
                data[key] = str(value)
        with open(filename, 'w') as file:
            json.dump(data, file, indent=1)
        return filename

    def chat(self):
        print('\n\nSystem: Chat started. Type "/exit" to exit.')
        uinput = ''
        while uinput != '/exit':
            print('\n\n')
            uinput = input('You: ')
            if uinput is not None and uinput != '/exit':
                print('\n\n')
                print(f'{self.name}: {self.respond(uinput)}')