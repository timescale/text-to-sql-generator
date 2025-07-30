import asyncio
import json
from pathlib import Path
import shutil
import click
from dotenv import load_dotenv
from typing import Optional

from generator.data import load_questions
from generator.database import get_results

from .generate import generate_questions, generate_prompt_base

load_dotenv()


@click.group()
def cli():
    pass


@cli.command(help="Generate questions")
@click.option("--count", help="Number of questions to generate", type=int, default=10)
@click.option("--prompt", help="Prompt file to use for generation", type=str)
def generate(count: int, prompt: Optional[str]) -> None:
    async def do():
        if prompt is not None:
            with open(prompt, "r") as f:
                loaded_prompt = f.read()
        else:
            loaded_prompt = await generate_prompt_base()
        await generate_questions(count, loaded_prompt)

    asyncio.run(do())


@cli.command(help="Generate prompt for LLM")
@click.option("--output", help="Output file for the prompt", type=str)
def generate_prompt(output: Optional[str]) -> None:
    async def do():
        prompt = await generate_prompt_base()
        if output is not None:
            with open(output, "w") as f:
                f.write(prompt)

    asyncio.run(do())


@cli.command(help="Export generated questions")
def export() -> None:
    questions = load_questions()
    base_dir = Path(__file__).parent.parent / "evals"
    if base_dir.exists():
        shutil.rmtree(base_dir)
    base_dir.mkdir()
    for qa in questions:
        d = base_dir / str(qa.id).rjust(4, "0")
        d.mkdir()
        d.joinpath("eval.json").write_text(
            json.dumps(
                {
                    "database": "postgres_air",
                    "question": qa.question,
                    "query": qa.answer,
                },
                indent=4,
            )
        )
        lines = []
        lines.append(f"# {qa.id}")
        lines.append("## Question")
        lines.append(f"[{qa.complexity}]")
        lines.append(f"{qa.question}")
        lines.append("## Answer")
        lines.append(f"```sql\n{qa.answer}\n```")
        lines.append("## Results")
        lines.append("First rows (LIMIT 10):")
        lines.append(f"```text\n{get_results(qa.answer)}\n```")
        d.joinpath("readme.md").write_text("\n\n".join(lines))


if __name__ == "__main__":
    cli()
