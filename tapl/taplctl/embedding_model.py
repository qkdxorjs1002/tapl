"""Pinned ONNX artifacts and the shared CPU encoder for TAPL semantic search."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


DIMENSION = 384
TOKEN_LIMIT = 128
DEFAULT_MODEL = "koen-e5-tiny-int8"
CACHE_ENV = "TAPL_MODEL_CACHE"


@dataclass(frozen=True)
class ModelSpec:
    repository: str
    revision: str
    onnx_path: str
    onnx_sha256: str
    tokenizer_sha256: str

    @property
    def fingerprint(self) -> str:
        # Changing a model file or its encoding contract requires a new index.
        contract = f"e5-query-passage:masked-mean:l2:f32le:{DIMENSION}:{TOKEN_LIMIT}:v1"
        return hashlib.sha256(
            f"{self.revision}:{self.onnx_sha256}:{self.tokenizer_sha256}:{contract}".encode("ascii")
        ).hexdigest()


MODELS = {
    DEFAULT_MODEL: ModelSpec(
        "exp-models/dragonkue-KoEn-E5-Tiny-ONNX", "5cf599a8cd6577f2f12a026130ad50132e472cfd",
        "onnx/model_qint8_arm64.onnx",
        "d463c9b1c29f3202d510e2836265d60f9e6e6dd518c5930ba865700646489bd4",
        "a6dd38d692ac1caa6d5dbc195d92f1f978b5c74ec60e02ed15fdf04404742fe3",
    ),
    "multilingual-e5-small-int8": ModelSpec(
        "Xenova/multilingual-e5-small", "761b726dd34fb83930e26aab4e9ac3899aa1fa78",
        "onnx/model_int8.onnx",
        "4d24e2bc01a447951524466ef533e52944bf48509e6552810bcee1a2711cb02c",
        "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    ),
}


def cache_root() -> Path:
    override = os.environ.get(CACHE_ENV)
    return Path(override).expanduser() if override else Path.home() / ".cache" / "tapl" / "models"


def _matches_sha256(path: Path, expected: str) -> bool:
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest() == expected
    except FileNotFoundError:
        return False


def _verified_file(path: Path, url: str, expected_sha256: str) -> Path:
    if _matches_sha256(path, expected_sha256):
        return path
    from http.client import IncompleteRead
    from time import sleep
    from urllib.error import HTTPError, URLError

    for backoff in (1, 2):
        try:
            return _download_file(path, url, expected_sha256)
        except (URLError, TimeoutError, ConnectionError, IncompleteRead) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                raise
            sleep(backoff)
    return _download_file(path, url, expected_sha256)


def _download_file(path: Path, url: str, expected_sha256: str) -> Path:
    from urllib.request import urlopen

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", delete=False) as target:
            temporary = Path(target.name)
            digest = hashlib.sha256()
            with urlopen(url, timeout=60) as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    target.write(chunk)
            if digest.hexdigest() != expected_sha256:
                raise ValueError(f"SHA-256 mismatch for {url}")
        try:
            os.replace(temporary, path)
        except PermissionError:
            # A concurrent process on Windows may already have installed and
            # memory-mapped these same bytes, preventing an identical replace.
            if not _matches_sha256(path, expected_sha256):
                raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


class Encoder:
    def __init__(self, model: str, root: Path) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        spec = MODELS[model]
        directory = root / model / spec.revision
        base = f"https://huggingface.co/{spec.repository}/resolve/{spec.revision}/"
        tokenizer = _verified_file(directory / "tokenizer.json", base + "tokenizer.json", spec.tokenizer_sha256)
        graph = _verified_file(directory / "model.onnx", base + spec.onnx_path, spec.onnx_sha256)

        self.tokenizer = Tokenizer.from_file(str(tokenizer))
        pad_id = self.tokenizer.token_to_id("<pad>")
        if pad_id is None:
            raise ValueError(f"{model} tokenizer is missing <pad>")
        self.tokenizer.enable_truncation(max_length=TOKEN_LIMIT)
        self.tokenizer.enable_padding(pad_id=pad_id, pad_token="<pad>")
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.log_severity_level = 3
        self.session = ort.InferenceSession(str(graph), sess_options=options, providers=["CPUExecutionProvider"])
        self.inputs = [value.name for value in self.session.get_inputs()]

    def encode(self, texts: list[str], *, query: bool) -> list[bytes]:
        """Encode one bounded batch as sqlite-vec compatible little-endian vectors."""
        import numpy as np

        prefix = "query: " if query else "passage: "
        encodings = self.tokenizer.encode_batch([prefix + text for text in texts])
        ids = np.asarray([value.ids for value in encodings], dtype=np.int64)
        masks = np.asarray([value.attention_mask for value in encodings], dtype=np.int64)
        inputs = {"attention_mask": masks, "input_ids": ids}
        if "token_type_ids" in self.inputs:
            inputs["token_type_ids"] = np.asarray([value.type_ids for value in encodings], dtype=np.int64)
        hidden = self.session.run(["last_hidden_state"], {name: inputs[name] for name in self.inputs})[0]
        if hidden.shape != (*ids.shape, DIMENSION):
            raise ValueError(f"unexpected ONNX output shape {hidden.shape}")

        weights = masks[:, :, None].astype(np.float32)
        pooled = (hidden * weights).sum(axis=1) / weights.sum(axis=1)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        if not np.isfinite(norms).all() or (norms == 0).any():
            raise ValueError("invalid embedding norm")
        return [vector.tobytes() for vector in (pooled / norms).astype("<f4", copy=False)]
