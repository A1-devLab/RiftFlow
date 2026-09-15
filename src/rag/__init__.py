"""RiftFlow 검색 및 Gemini 답변 (담당: 이찬영).

다른 모듈은 docs/interfaces.md 에 적힌 대로 answer_question 만 쓴다.
"""
from .api import answer_question

__all__ = ['answer_question']
