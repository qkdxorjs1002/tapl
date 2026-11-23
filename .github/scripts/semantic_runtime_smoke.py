"""Check both installed CPU models with an English query against a Korean record."""

from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sysconfig
import tempfile

from taplctl import config, db, embeddings


def run_cli(command: list[str], root: Path, *arguments: str) -> dict:
    result = subprocess.run(
        [*command, *arguments, "--json"], cwd=root,
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    if result.returncode:
        raise RuntimeError(f"taplctl {arguments} exited {result.returncode}: {result.stdout} {result.stderr}")
    return json.loads(result.stdout)


def main() -> None:
    cli = Path(sysconfig.get_path("scripts")) / ("taplctl.exe" if os.name == "nt" else "taplctl")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "search.db"
        settings = root / "config.toml"
        settings.write_text('[search]\nmode = "semantic"\nsemantic_provider = "local"\n', encoding="utf-8")
        command = [str(cli), "--db", str(database), "--config", str(settings)]
        with closing(db.connect(database)) as conn:
            db.upsert_item(conn, kind="TASK", stable_id="TASK-001", title="백업에서 데이터 복구")
            default = "koen-e5-tiny-int8"
            for model in (default, "multilingual-e5-small-int8"):
                if model != default:
                    run_cli(command, root, "config", "set", "search.model", model)
                    preview = run_cli(command, root, "reindex", "--dry-run")
                    if preview.get("indexed_model") != default or not preview["needs_reindex"]:
                        raise ValueError(f"Model switch did not report the old index: {preview}")
                indexed = run_cli(command, root, "reindex")
                if indexed.get("indexed") != 1 or indexed.get("indexed_model") != model:
                    raise ValueError(f"Incorrect index: {indexed}")
                found = embeddings.search(conn, "restore a database backup", search_config=config.load(settings).search)
                if found["mode"] != "semantic" or [row["stable_id"] for row in found["results"]] != ["TASK-001"]:
                    raise ValueError(f"Semantic CPU retrieval failed: {found}")
                print(f"Indexed and retrieved a Korean record with {model} on CPU.")


if __name__ == "__main__":
    main()
