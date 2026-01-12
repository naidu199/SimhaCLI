from datetime import datetime
import uuid
from client.llm_client import LLMClinet
from config.config import Config
from context.manager import ContextManager
from tools.registry import create_default_registry


class Session:
    def __init__(self, config: Config) -> None:
        self.config: Config = config
        self.client: LLMClinet = LLMClinet(config=self.config)
        self.context_manager = ContextManager(config=self.config)
        self.tool_registry = create_default_registry()
        self.session_id: str = str(uuid.uuid4())
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

        self._turn_count: int = 0

    def incremenet_trun_count(self) -> None:
        self._turn_count += 1
        self.updated_at = datetime.now()

        return self._turn_count
