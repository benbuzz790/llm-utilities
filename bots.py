from abc import ABC, abstractmethod
from enum import Enum
import conversation_node as CN
import bot_mailbox as MB
import datetime as DT
import re
import json
import os
from typing import Optional, Union, Type, Dict, Any


class Engines(Enum):
    """
    Enum class representing different AI model engines.
    """
    GPT4 = "gpt-4"
    GPT432k = "gpt-4-32k"
    GPT35 = "gpt-3.5-turbo"
    CLAUDE3OPUS = "claude-3-opus-20240229"
    CLAUDE3SONNET = "claude-3-sonnet-20240229"

    @staticmethod
    def get_bot_class(model_engine: "Engines") -> Type["BaseBot"]:
        """
        Returns the bot class based on the model engine.
        """
        if model_engine in [Engines.GPT4, Engines.GPT35, Engines.GPT432k]:
            return GPTBot
        elif model_engine in [Engines.CLAUDE3OPUS, Engines.CLAUDE3SONNET]:
            return AnthropicBot
        else:
            raise ValueError(f"Unsupported model engine: {model_engine}")


class BaseBot(ABC):
    """
    Abstract base class for bot implementations.
    """

    def __init__(
        self,
        api_key: Optional[str],
        model_engine: Engines,
        max_tokens: int,
        temperature: float,
        name: str,
        role: str,
        role_description: str,
    ):
        self.api_key = api_key
        self.name = name
        self.model_engine = model_engine
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.role = role
        self.role_description = role_description
        self.conversation: Optional[CN.ConversationNode] = None

    def respond(self, content: str, role: str = "user") -> str:
        """
        Generates a response based on the given content and role.
        """
        reply, self.conversation = self.cvsn_respond(
            text=content, cvsn=self.conversation, role=role
        )
        return reply

    def cvsn_respond(
        self,
        text: Optional[str] = None,
        cvsn: Optional[CN.ConversationNode] = None,
        role: str = "user",
    ) -> Union[str, CN.ConversationNode]:
        """
        Generates a response based on the conversation node and text.
        """
        if cvsn is not None and text is not None:
            try:
                cvsn = cvsn.add_reply(text, role)
                response_text, response_role, _ = self._send_message(cvsn)
                cvsn = cvsn.add_reply(response_text, response_role)
                return response_text, cvsn
            except Exception as e:
                raise e
        elif cvsn is not None:
            try:
                response_text, response_role, _ = self._send_message(cvsn)
                cvsn = cvsn.add_reply(response_text, response_role)
                return response_text, cvsn
            except Exception as e:
                raise e
        elif text is not None:
            c = CN.ConversationNode(role=role, content=text)
            return self.cvsn_respond(cvsn=c)
        elif text is None and cvsn is not None:
            try:
                response_text, response_role, _ = self._send_message(cvsn)
                cvsn = cvsn.add_reply(response_text, response_role)
                return response_text, cvsn
            except Exception as e:
                raise e
        else:
            raise Exception

    @abstractmethod
    def _send_message(self, cvsn: CN.ConversationNode) -> tuple:
        """
        Sends a message to the bot's mailbox (to be implemented by subclasses).
        """
        pass

    def formatted_datetime(self) -> str:
        """
        Returns the current date and time in a formatted string.
        """
        now = DT.datetime.now()
        return now.strftime("%Y.%m.%d-%H.%M.%S")

    def save_conversation_tree(self, conversation_root: CN.ConversationNode) -> None:
        """
        Saves the conversation tree to a file.
        """
        filename = f"{self.name}@{self.formatted_datetime()}.cvsn"
        data = conversation_root.to_dict()
        with open(filename, "w") as file:
            json.dump(data, file)

    @classmethod
    def load(cls, filepath: str) -> "BaseBot":
        """
        Loads a bot instance or conversation from a file.
        """
        _, extension = os.path.splitext(filepath)

        if extension == ".bot":
            with open(filepath, "r") as file:
                data = json.load(file)

            bot_class = globals()[data["bot_class"]]
            bot = bot_class(
                api_key=None,
                model_engine=Engines(data["model_engine"]),
                max_tokens=data["max_tokens"],
                temperature=data["temperature"],
                name=data["name"],
                role=data["role"],
                role_description=data["role_description"],
            )

            if data["conversation"]:
                bot.conversation = CN.ConversationNode.from_dict(data["conversation"])

            return bot

        elif extension == ".cvsn":
            with open(filepath, "r") as file:
                conversation_data = json.load(file)

            conversation_node = CN.ConversationNode.from_dict(conversation_data)
            return conversation_node

        else:
            raise ValueError(f"Unsupported file extension: {extension}")

    def save(self, filename: Optional[str] = None) -> None:
        """
        Saves the bot instance to a file.
        """
        now = DT.datetime.now()
        formatted_datetime = now.strftime("%Y.%m.%d-%H.%M.%S")
        if filename is None:
            filename = f"{self.name}@{formatted_datetime}.bot"
        data = {
            "bot_class": self.__class__.__name__,
            "name": self.name,
            "model_engine": self.model_engine.value,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "role": self.role,
            "role_description": self.role_description,
            "conversation": self.conversation.to_dict() if self.conversation else None,
        }
        with open(filename, "w") as file:
            json.dump(data, file)

    def converse(self) -> None:
        """
        Starts an interactive conversation with the bot in the console.
        """
        self.sys_say("Begin Conversation")

        while True:
            user_input = input("You: ")
            match user_input:
                case "/debug":
                    print("---")
                    self.sys_say("Debug:")
                    print("\n")
                    self.sys_say(
                        f"Name:{self.name}, Role:{self.role}, Description:{self.role_description}"
                    )
                    print("\n")
                    print("\n")
                    print(self.conversation.root().to_string())
                    print("\n")
                    print("---")
                case "/break":
                    self.sys_say("conversation ended")
                    break
                case "/save":
                    self.save()
                case "/load":
                    self.sys_say("Enter path")
                    self = self.load(input("You: "))
                case _:
                    if self.conversation is not None:
                        self.conversation = self.conversation.add_reply(user_input, "user")
                    else:
                        self.conversation = CN.ConversationNode(role="user", content=user_input)
                    response, self.conversation = self.cvsn_respond(cvsn=self.conversation)
                    self.say(response)

    def sys_say(self, string: str) -> None:
        """
        Prints a message from the system.
        """
        print(f"System: {string}")

    def say(self, string: str) -> None:
        """
        Prints a message from the bot.
        """
        print(f"{self.name}: {string}")


class GPTBot(BaseBot):
    """
    ChatGPT-based bot implementation.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_engine: Engines = Engines.GPT4,
        max_tokens: int = 4096,
        temperature: float = 0.9,
        name: str = "bot",
        role: str = "assistant",
        role_description: str = "a friendly AI assistant",
    ):
        super().__init__(api_key, model_engine.value, max_tokens, temperature, name, role, role_description)
        match model_engine:
            case Engines.GPT4 | Engines.GPT35 | Engines.GPT432k:
                self.mailbox = MB.OpenAIMailbox(verbose=True)
            case _:
                raise Exception(f"model_engine: {model_engine} not found")

    @classmethod
    def load(cls, filepath: str) -> "GPTBot":
        """
        Loads a GPTBot instance from a file.
        """
        return super().load(filepath)

    def _send_message(
        self, cvsn: CN.ConversationNode
    ) -> tuple[str, str, Dict[str, Any]]:
        """
        Sends a message to the bot's mailbox using the OpenAI API.
        """
        return self.mailbox.send_message(
            cvsn, self.model_engine, self.max_tokens, self.temperature, self.api_key
        )


class AnthropicBot(BaseBot):
    """
    Anthropic-based bot implementation.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_engine: Engines = Engines.CLAUDE3OPUS,
        max_tokens: int = 4096,
        temperature: float = 0.9,
        name: str = "bot",
        role: str = "assistant",
        role_description: str = "a friendly AI assistant",
    ):
        super().__init__(api_key, model_engine.value, max_tokens, temperature, name, role, role_description)
        match model_engine:
            case Engines.CLAUDE3OPUS | Engines.CLAUDE3SONNET:
                self.mailbox = MB.AnthropicMailbox(verbose=True)
            case _:
                raise Exception(f"model_engine: {model_engine} not found")

    @classmethod
    def load(cls, filepath: str) -> "AnthropicBot":
        """
        Loads an AnthropicBot instance from a file.
        """
        return super().load(filepath)

    def _send_message(
        self, cvsn: CN.ConversationNode
    ) -> tuple[str, str, Dict[str, Any]]:
        """
        Sends a message to the bot's mailbox using the Anthropic API.
        """
        return self.mailbox.send_message(
            cvsn, self.model_engine, self.max_tokens, self.temperature, self.api_key
        )


def remove_code_blocks(text: str) -> list[str]:
    """
    Extracts the content inside code blocks from the given text.
    """
    pattern = r"```(?:[a-zA-Z0-9_+-]+)?\s*([\s\S]*?)```"
    code_blocks = []
    
    while True:
        match = re.search(pattern, text)
        if match:
            code_block = match.group(1).strip()
            code_blocks.append(code_block)
            text = text[:match.start()] + text[match.end():]
        else:
            break
    
    return code_blocks


if __name__ == "__main__":
    GPTBot().converse()