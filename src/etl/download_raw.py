import lzma
import os
from pathlib import Path
import shutil
import requests

from src.cli.console import print_banner, print_msg, status, step_progress
from src.config import CARDS_CSV_PATH, RAW_DATA_DIR

URLS = {
    "AllPrices.json.xz": "https://mtgjson.com/api/v5/AllPrices.json.xz",
    "cards.csv.xz": "https://mtgjson.com/api/v5/csv/cards.csv.xz",
}


def _download_file(url: str, destination: Path, filename: str) -> None:
    print_msg(
        f"[bold cyan]↓ Downloading[/bold cyan] [bold white]{filename}[/bold white] from [dim]{url}[/dim]",
        f"Downloading {filename}...",
    )
    response = requests.get(url, stream=True, timeout=120)
    response.raise_for_status()
    total_size = int(response.headers.get("content-length", 0))

    with step_progress(f"Fetching {filename}", total=total_size, download=True) as task:
        with open(destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    task.update(advance=len(chunk))


def _decompress_cards_csv(compressed_path: Path, extracted_path: Path) -> None:
    with status(
        f"[bold yellow]Decompressing {compressed_path.name} -> cards.csv...[/bold yellow]",
        f"Decompressing {compressed_path.name}...",
    ):
        with lzma.open(compressed_path, "rb") as f_in, open(extracted_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out, length=1024 * 1024)
        os.remove(compressed_path)
    print_msg(
        f"  [bold green]✓ Ready:[/bold green] [white]{extracted_path}[/white]\n",
        f"Ready: {extracted_path}\n",
    )


def download_feeds() -> None:
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print_banner(
        "MTGJSON Streaming Data Ingestion Feed",
        "Acquiring bulk price matrices and comprehensive card dimension tables",
    )

    for filename, url in URLS.items():
        compressed_path = RAW_DATA_DIR / filename
        _download_file(url, compressed_path, filename)

        if filename == "cards.csv.xz":
            _decompress_cards_csv(compressed_path, CARDS_CSV_PATH)
        else:
            print_msg(
                f"  [bold green]✓ Ready (compressed archive):[/bold green] [white]{compressed_path}[/white]\n",
                f"Ready (retained compressed): {compressed_path}\n",
            )


if __name__ == "__main__":
    download_feeds()
