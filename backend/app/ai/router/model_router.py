from enum import StrEnum

from pydantic import BaseModel

from app.config import Settings


class TaskType(StrEnum):
    DOCUMENT_CLASSIFICATION = "document_classification"
    METADATA_EXTRACTION = "metadata_extraction"
    QUERY_REWRITE = "query_rewrite"
    BASIC_SUMMARIZATION = "basic_summarization"
    SIMPLE_QUESTION = "simple_question"
    VISION_DOCUMENT_ANALYSIS = "vision_document_analysis"
    POLICY_REASONING = "policy_reasoning"
    CLAIM_DENIAL_ANALYSIS = "claim_denial_analysis"
    CONTRADICTION_ANALYSIS = "contradiction_analysis"
    EVIDENCE_SYNTHESIS = "evidence_synthesis"
    APPEAL_GENERATION = "appeal_generation"
    ORCHESTRATION = "orchestration"
    EMBEDDING = "embedding"
    SAFETY = "safety"


class ModelConfig(BaseModel):
    model: str
    env_name: str
    fallback: str = ""
    temperature: float = 0.1
    max_tokens: int = 4096
    parameters: dict = {}


class NvidiaModelRouter:
    REASONING_TASKS = {
        TaskType.POLICY_REASONING, TaskType.CLAIM_DENIAL_ANALYSIS,
        TaskType.CONTRADICTION_ANALYSIS, TaskType.EVIDENCE_SYNTHESIS,
        TaskType.APPEAL_GENERATION, TaskType.ORCHESTRATION,
    }

    def __init__(self, settings: Settings):
        self.settings = settings

    def select_model(self, task: TaskType) -> ModelConfig:
        s = self.settings
        if task == TaskType.EMBEDDING:
            model, env, fallback = s.nvidia_embedding_model, "NVIDIA_EMBEDDING_MODEL", ""
        elif task == TaskType.VISION_DOCUMENT_ANALYSIS:
            model, env, fallback = s.nvidia_vision_model, "NVIDIA_VISION_MODEL", ""
        elif task == TaskType.SAFETY:
            model, env, fallback = s.nvidia_safety_model, "NVIDIA_SAFETY_MODEL", ""
        elif task in self.REASONING_TASKS:
            model, env, fallback = (s.nvidia_reasoning_model, "NVIDIA_REASONING_MODEL",
                                    s.nvidia_reasoning_fallback_model)
        else:
            model, env, fallback = s.nvidia_fast_model, "NVIDIA_FAST_MODEL", s.nvidia_fast_fallback_model
        return ModelConfig(model=model, env_name=env, fallback=fallback,
                           max_tokens=s.max_output_tokens,
                           parameters=s.nvidia_model_parameters.get(model, {}))
