# Question Generator for Text-to-SQL Datasets

This tool can be used to generate questions on datasets for text-to-sql.

## Requirements

To use this table, you will need:

* Python
* [uv](https://github.com/astral-sh/uv)
* A PostgreSQL database with [pgai](https://github.com/timescale/pgai) installed

## Setup

```bash
uv sync
```

After loading the dataset into the database, you will need to initialize the
semantic catalog (TODO: link to docs) for your database. You can use the
following function to generate the descriptions for your database, assuming
everything is in the `public` schema:

```sql
select
  format('select x.sql from ai.generate_description(%L) x;', x.oid::regclass)
, format('select x.sql from ai.generate_column_descriptions(%L) x;', x.oid::regclass)
from
(
    select k.*
    from pg_class k
    inner join pg_namespace n on (k.relnamespace = n.oid)
    where n.nspname = 'public'
    and k.relkind in ('r', 'p', 'v', 'm')
    order by k.relname
);
```

## Usage

### Generate system prompt

```text
$ uv run python3 -m generator generate-prompt --help
Usage: python -m generator generate-prompt [OPTIONS]

  Generate prompt for LLM

Options:
  --output TEXT  Output file for the prompt
  --help         Show this message and exit.
```

You can use the `generate-prompt` command to generate a system prompt that can
be used in subsequent runs of the `generate` command. If you don't do this,
then when you call `generate`, a prompt is automatically generated.

### Generate questions

```text
$ uv run python3 -m generator generate --help
Usage: python -m generator generate [OPTIONS]

  Generate questions

Options:
  --count INTEGER  Number of questions to generate
  --prompt TEXT    Prompt file to use for generation
  --help           Show this message and exit.
```

Use this function to generate X number of questions. Whatever value you pass
to `count` is split evenly to generate X easy, Y intermediate, and Z hard
questions. For example, if you pass `--count 5`, then you will get 2 easy,
2 intermediate, and 1 hard questions generated.

All generated questions are stored in the `questions` table in the
`./data.sqlite` file.

This function does the following to generate questions:

1. If a prompt file was not passed in, then generate a system prompt to use.
2. Going in order of easy, intermediate, and then hard, ask the LLM to generate
  question for a given complexity.
3. Use the `ai.text_to_sql` function to generate a SQL query to answer the
  question.
4. Run the generated SQL query and get the first 10 sample rows, or any errors
  that occured during execution.
5. Ask the LLM if the generated SQL adequately answers the question, returning
  the following information:
  a. a reason why the generated query was or was not adequate
  b. if not adequate, a modified SQL query that properly answers the question
  c. if we can even fix the SQL query, or if we should generate a new question
6. If the query was inadequate and not fixable, then return to (2) and generate
  a new question.
7. If the query was inadequate, but we got a modified SQL back, then run that
  modified SQL to get new results or error, and then go back to (5).
8. If the query was deemed adequate, save the `[question, query]` tuple to the
  `questions` table in `./data.sqlite`.
