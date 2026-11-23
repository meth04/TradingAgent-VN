import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

from .cli import cli

if __name__ == "__main__":
    cli()
