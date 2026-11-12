"""Extraction PDF depuis un Unity Catalog Volume accessible via /Volumes."""
from pathlib import Path
import fitz


def extract_project_pdf(project_id: str, pdf_path: str) -> dict:
    path = Path(pdf_path).resolve()
    if not str(path).startswith('/Volumes/') or path.suffix.lower() != '.pdf':
        raise ValueError('Le document doit être un PDF situé dans /Volumes/')
    if not path.is_file():
        raise FileNotFoundError(path)
    pages = []
    with fitz.open(path) as document:
        for number, page in enumerate(document, start=1):
            pages.append({'page': number, 'text': page.get_text('text').strip()})
    return {'project_id': project_id, 'file_name': path.name,
            'source_path': str(path), 'pages': pages,
            'page_count': len(pages), 'text': '\n\n'.join(p['text'] for p in pages)}
