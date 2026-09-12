import hashlib
import json
import re
from pathlib import Path

from app.agent.contracts import Citation
from app.core.config import Settings
from app.core.errors import DomainError
from app.services.policy import PolicyEngine


def terms(text: str) -> set[str]:
    text = text.lower()
    words = set(re.findall(r"[a-z_]+|[0-9]+", text))
    for part in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(part[i : i + 2] for i in range(max(1, len(part) - 1)))
    return words


class PolicyKnowledge:
    def __init__(self, settings: Settings):
        self.version = PolicyEngine(settings).version
        self.documents = {}
        self.index = {}
        records = json.loads(Path(__file__).with_name("knowledge.json").read_text(encoding="utf-8"))
        for record in records:
            content = record["text"].format(
                return_days=settings.return_window_days,
                quality_days=settings.quality_window_days,
                threshold=f"{settings.high_amount_threshold:.2f}",
            )
            doc = Citation(
                id=record["id"],
                title=record["title"],
                version=self.version,
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                source=f"/agent/policies/{record['id']}",
            )
            self.documents[doc.id] = doc
            # Generic words in policy prose (e.g. 订单) used to promote unrelated
            # documents. Curated keywords carry retrieval intent; full evidence
            # remains unchanged in returned citations and PolicyEngine.
            self.index[doc.id] = terms(record["keywords"])

    def search(self, query: str) -> list[Citation]:
        query_terms = terms(query)
        matches = [(len(query_terms & self.index[key]), doc) for key, doc in self.documents.items()]
        return [doc for score, doc in sorted(matches, key=lambda x: (-x[0], x[1].id))[:3] if score > 0]

    def get(self, document_id: str) -> Citation:
        if document_id not in self.documents:
            raise DomainError("POLICY_NOT_FOUND", "政策文档不存在", 404)
        return self.documents[document_id]
