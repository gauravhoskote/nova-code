import os
from typing import Iterator, Literal, Optional

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.chat_history import InMemoryChatMessageHistory

MODEL_ID = "global.amazon.nova-2-lite-v1:0"

ThinkingEffort = Literal["low", "medium", "high", "auto"]


def _chunk_text(chunk) -> str:
    """Extract text from a LangChain streaming chunk.

    ChatBedrockConverse can return content as either a plain string
    or a list of content blocks e.g. [{'type': 'text', 'text': '...'}].
    """
    content = chunk.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


class NovaClient:
    def __init__(
        self,
        region: str = None,
        thinking_effort: Optional[ThinkingEffort] = None,
    ):
        self.model_id = MODEL_ID
        self.region = region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        self.thinking_effort = thinking_effort
        self._llm = None
        self.history = InMemoryChatMessageHistory()

    @property
    def llm(self) -> ChatBedrockConverse:
        if self._llm is None:
            self._llm = self._build_llm()
        return self._llm

    def _build_llm(self) -> ChatBedrockConverse:
        kwargs: dict = dict(
            model=self.model_id,
            region_name=self.region,
            # max_tokens=4096,
        )
        if self.thinking_effort:
            # "auto" = enable thinking at low effort (Bedrock doesn't have an auto tier)
            api_effort = "low" if self.thinking_effort == "auto" else self.thinking_effort
            # "high" effort forbids temperature/topP/topK per AWS docs
            if api_effort != "high":
                kwargs["temperature"] = 0.7
            kwargs["additional_model_request_fields"] = {
                "reasoningConfig": {
                    "type": "enabled",
                    "maxReasoningEffort": api_effort,
                }
            }
        else:
            kwargs["temperature"] = 0.7
        return ChatBedrockConverse(**kwargs)

    def set_thinking(self, effort: Optional[ThinkingEffort]):
        self.thinking_effort = effort
        self._llm = None  # rebuilt lazily on next call

    def load_messages(self, messages: list):
        """Pre-populate history from a persisted session."""
        for msg in messages:
            self.history.add_message(msg)

    def clear_history(self):
        self.history.clear()

    def chat(self, user_input: str, system: str = None) -> Iterator[str]:
        """Stream a response and persist both turns to history."""
        self.history.add_user_message(user_input)

        messages = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.extend(self.history.messages)

        full_response = ""
        for chunk in self.llm.stream(messages):
            text = _chunk_text(chunk)
            if text:
                full_response += text
                yield text

        self.history.add_ai_message(full_response)

    def ask_once(self, prompt: str, system: str = None) -> Iterator[str]:
        """Single-shot stream — no history read or written."""
        messages = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(HumanMessage(content=prompt))

        for chunk in self.llm.stream(messages):
            text = _chunk_text(chunk)
            if text:
                yield text


