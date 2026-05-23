"""Upload and list documents."""

from __future__ import annotations

import uuid

import pixeltable as pxt
from fastapi import APIRouter

from api_contract import DocumentInfo, DocumentsResponse, UploadRequest, UploadResponse

router = APIRouter()


@router.post('/upload', response_model=UploadResponse)
def upload(req: UploadRequest) -> UploadResponse:
    docs = pxt.get_table('kb.documents')
    modality = 'image' if req.image_url else 'text'
    row = {
        'text': req.content or '',
        'source': req.source,
        'modality': modality,
        'metadata': req.metadata,
        'image': req.image_url,
    }
    docs.insert([row])
    doc_id = str(uuid.uuid4())
    return UploadResponse(id=doc_id, source=req.source, modality=modality)


@router.get('/documents', response_model=DocumentsResponse)
def list_documents() -> DocumentsResponse:
    docs = pxt.get_table('kb.documents')
    rows = docs.select(docs.source, docs.modality).collect()
    items = [
        DocumentInfo(id=str(uuid.uuid4()), source=r['source'], modality=r['modality'])
        for r in rows.to_dicts()
    ]
    return DocumentsResponse(documents=items, total=len(items))
