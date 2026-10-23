"""
Upload bank_documents/HBL.md to Supabase.
Uses OpenAI embeddings without importing langchain_openai.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client


# Project ke main folder se .env aur Markdown file read karein.
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

MD_FILE = BASE_DIR / "bank_documents" / "HBL.md"

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


def split_text(text: str) -> list[str]:
    chunks = []
    start = 0

    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end == len(text):
            break

        start = end - CHUNK_OVERLAP

    return chunks


def main():
    if not MD_FILE.exists():
        raise FileNotFoundError(f"File not found: {MD_FILE}")

    text = MD_FILE.read_text(encoding="utf-8-sig")

    if not text.strip():
        raise ValueError("HBL.md is empty.")

    required = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "OPENAI_API_KEY",
    ]

    missing = [
        name for name in required
        if not os.getenv(name)
        or "YOUR_" in os.getenv(name, "")
    ]

    if missing:
        raise ValueError(
            "Check these .env variables: " + ", ".join(missing)
        )

    supabase = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )

    openai_client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"]
    )

    chunks = split_text(text)

    print(f"File found: {MD_FILE.name}")
    print(f"Total chunks: {len(chunks)}", flush=True)

    for i, chunk in enumerate(chunks, start=1):
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=chunk,
            dimensions=384,
        )

        embedding = response.data[0].embedding

        supabase.table("documents").insert(
            {
                "content": chunk,
                "metadata": {
                    "source": MD_FILE.name,
                    "chunk_number": i,
                },
                "embedding": embedding,
            }
        ).execute()

        print(
            f"Uploaded {i}/{len(chunks)}",
            flush=True,
        )

    print("HBL Markdown data uploaded to Supabase!")


if __name__ == "__main__":
    main()