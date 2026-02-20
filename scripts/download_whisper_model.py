"""Download faster-whisper-base from Hugging Face to whisper-model/."""

from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ID = "guillaumekln/faster-whisper-base"
LOCAL_DIR = Path(__file__).resolve().parent.parent / "whisper-model"


def main() -> None:
    print(f"Downloading {REPO_ID} to {LOCAL_DIR} ...")
    snapshot_download(repo_id=REPO_ID, local_dir=str(LOCAL_DIR))
    print(f"Done. Model is in {LOCAL_DIR}")
    print("Set in .env: WHISPER_MODEL=whisper-model  (or the full path)")


if __name__ == "__main__":
    main()
