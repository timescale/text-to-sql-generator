import click
from dotenv import load_dotenv
from typing import Optional

from .generate import generate_questions, generate_prompt_base

load_dotenv()


@click.group()
def cli():
    pass


@cli.command(help="Generate questions")
@click.option("--count", help="Number of questions to generate", type=int, default=10)
@click.option("--prompt", help="Prompt file to use for generation", type=str)
def generate(count: int, prompt: Optional[str]) -> None:
    if prompt is not None:
        with open(prompt, "r") as f:
            loaded_prompt = f.read()
    else:
        loaded_prompt = generate_prompt_base()
    generate_questions(count, loaded_prompt)


@cli.command(help="Generate prompt for LLM")
@click.option("--output", help="Output file for the prompt", type=str)
def generate_prompt(output: Optional[str]) -> None:
    prompt = generate_prompt_base()
    if output is not None:
        with open(output, "w") as f:
            f.write(prompt)

if __name__ == "__main__":
    cli()
