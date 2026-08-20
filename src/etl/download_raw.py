import os
import requests
import lzma
import shutil
from pathlib import Path

try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False

URLS = {
    "AllPrices.json.xz": "https://mtgjson.com/api/v5/AllPrices.json.xz",
    "cards.csv.xz": "https://mtgjson.com/api/v5/csv/cards.csv.xz"
}


def download_feeds():
    raw_dir = os.path.join("data", "raw")
    os.makedirs(raw_dir, exist_ok=True)

    if HAS_RICH:
        console.print(Panel(
            "[bold white]MTGJSON Streaming Data Ingestion Feed[/bold white]\n"
            "[dim]Acquiring bulk price matrices and comprehensive card dimension tables[/dim]",
            box=box.ROUNDED,
            border_style="cyan"
        ))

    for filename, url in URLS.items():
        compressed_path = os.path.join(raw_dir, filename)

        if HAS_RICH:
            console.print(f"[bold cyan]↓ Downloading[/bold cyan] [bold white]{filename}[/bold white] from [dim]{url}[/dim]")
            response = requests.get(url, stream=True)
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(complete_style="green", finished_style="bold green"),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console
            ) as progress:
                task = progress.add_task(f"Fetching {filename}", total=total_size)
                with open(compressed_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))
        else:
            print(f"Downloading {filename}...")
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with open(compressed_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

        if filename == "cards.csv.xz":
            extracted_path = os.path.join(raw_dir, "cards.csv")
            if HAS_RICH:
                with console.status(f"[bold yellow]Decompressing {filename} -> cards.csv...[/bold yellow]"):
                    with lzma.open(compressed_path, "rb") as f_in:
                        with open(extracted_path, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out, length=1024 * 1024)
                    os.remove(compressed_path)
                console.print(f"  [bold green]✓ Ready:[/bold green] [white]{extracted_path}[/white]\n")
            else:
                print(f"Decompressing {filename}...")
                with lzma.open(compressed_path, "rb") as f_in:
                    with open(extracted_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out, length=1024 * 1024)
                os.remove(compressed_path)
                print(f"Ready: {extracted_path}\n")
        else:
            if HAS_RICH:
                console.print(f"  [bold green]✓ Ready (compressed archive):[/bold green] [white]{compressed_path}[/white]\n")
            else:
                print(f"Ready (retained compressed): {compressed_path}\n")


if __name__ == "__main__":
    download_feeds()