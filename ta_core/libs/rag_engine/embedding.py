import asyncio
import sys

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from .config import settings

_embedding_model = None


def _resolve_embedding_device() -> str:
    if torch.cuda.is_available():
        return "cuda"

    if torch.backends.cuda.is_built():
        # Log the fallback reason explicitly so operators do not mistake a CUDA
        # wheel install for a usable GPU runtime inside Docker/WSL.
        print(
            "CUDA-enabled PyTorch is installed but no GPU runtime is visible; "
            "falling back to CPU. Check NVIDIA driver passthrough, `nvidia-smi`, "
            "and `/dev/nvidia*` inside the current environment.",
            file=sys.stderr,
        )
    return "cpu"


def load_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        device = _resolve_embedding_device()
        print(
            f"Loading embedding model: {settings.EMBEDDING_MODEL} (device={device})...",
            file=sys.stderr,
        )
        _embedding_model = SentenceTransformer(
            settings.EMBEDDING_MODEL,
            trust_remote_code=True,
            device=device,
        )
    return _embedding_model

async def bge_m3_embedding(texts: list[str]) -> np.ndarray:
    model = load_embedding_model()
    loop = asyncio.get_event_loop()
    
    embeddings = await loop.run_in_executor(
        None, 
        lambda: model.encode(texts, normalize_embeddings=True, batch_size=2)
    )
    return embeddings