import shutil
from pathlib import Path

def clean_data() -> None:
    """Removes the entire data directory to reset pipeline state."""
    app_dir = Path(__file__).resolve().parent
    data_dir = app_dir / "data"

    if not data_dir.exists():
        print(f"Data directory {data_dir} does not exist. Nothing to clean.")
        return

    print(f"Cleaning up data directory: {data_dir}")
    try:
        shutil.rmtree(data_dir, ignore_errors=True)
        print("Cleanup complete! All audio, transcripts, chunks, logs, and state have been removed.")
    except Exception as e:
        print(f"Error during cleanup: {e}")
        print("Ensure the GUI is closed before running cleanup to avoid file locking issues on Windows.")

if __name__ == "__main__":
    clean_data()
