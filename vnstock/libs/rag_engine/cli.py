import click
import asyncio
from .ingest import run_ingest
from .retrieval import query_func
from .evaluate import run_eval

@click.group()
def cli():
    pass

@cli.command(name='index')
@click.option('--dir', required=True, type=click.Path(exists=True))
@click.option('--pattern', default='*.ocr_text.txt')
def index_cmd(dir, pattern):
    """Index documents."""
    run_ingest(dir, pattern)

@cli.command(name='ask')
@click.argument('question')
@click.option('--mode', default='hybrid', type=click.Choice(['global', 'local', 'hybrid']))
def ask_cmd(question, mode):
    """Query documents."""
    async def _run():
        _, ans = await query_func(None, question, mode)
        return ans
    print(f"\nANSWER: {asyncio.run(_run())}")

@cli.command(name='eval')
@click.option('--dir', default='data')
def eval_cmd(dir):
    """Run Ragas evaluation."""
    run_eval(dir)

if __name__ == '__main__':
    cli()