# Question Generator for Text-to-SQL Datasets

This tool can be used to generate questions on datasets for text-to-sql.

## Requirements

To use this table, you will need:

* Python
* [uv](https://github.com/astral-sh/uv)
* A PostgreSQL database with [pgai semantic-catalog](https://github.com/timescale/pgai/blob/main/docs/semantic_catalog/quickstart.md) setup

It's expected that for your dataset, you have setup the semantic-catalog such that
all objects have had descriptions created/generated.

## Setup

After cloning the repo, to install dependencies:

```bash
uv sync
cp .env.sample .env
```

You will then need to modify `DB_URL` to point at the dataset you want to generate questions for, and add
value for `OPENAI_API_KEY`.

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

## Quickstart

To demonstrate the repo, we provide quickstart guide. For this, we will use the
[Analyze the Bitcoin Blockchain](https://docs.tigerdata.com/tutorials/latest/blockchain-analyze/)
guide from Tiger Cloud docs.

First, start up a TimescaleDB docker instance:

```bash
docker run -d --name postgres-bitcoin \
    -p 127.0.0.1:5432:5432 \
    -e POSTGRES_HOST_AUTH_METHOD=trust \
    -e POSTGRES_DB=bitcoin \
    timescale/timescaledb-ha:pg17
```

Next is to setup the DB:

```bash
psql -h localhost -U postgres -d bitcoin -c "
CREATE TABLE transactions (
   time TIMESTAMPTZ NOT NULL,
   block_id INT,
   hash TEXT,
   size INT,
   weight INT,
   is_coinbase BOOLEAN,
   output_total BIGINT,
   output_total_usd DOUBLE PRECISION,
   fee BIGINT,
   fee_usd DOUBLE PRECISION,
   details JSONB
) WITH (
   tsdb.hypertable,
   tsdb.partition_column='time',
   tsdb.segmentby='block_id',
   tsdb.orderby='time DESC'
);

CREATE INDEX hash_idx ON public.transactions USING HASH (hash);
CREATE INDEX block_idx ON public.transactions (block_id);
CREATE UNIQUE INDEX time_hash_idx ON public.transactions (time, hash);
"
```

Next, download the `bitcoin_sample.zip`, unzip it, and then copy it into the DB.
As there's over a million rows, it may take a few minutes to load the data.

```bash
wget https://assets.timescale.com/docs/downloads/bitcoin-blockchain/bitcoin_sample.zip
unzip bitcoin_sample.zip
psql -h localhost -U postgres -d bitcoin -c "\COPY transactions FROM 'tutorial_bitcoin_sample.csv' CSV HEADER;"
```

Then create the continuous aggregates:

```bash
psql -h localhost -U postgres -d bitcoin -c "
CREATE MATERIALIZED VIEW one_hour_transactions
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', time) AS bucket,
   count(*) AS tx_count,
   sum(fee) AS total_fee_sat,
   sum(fee_usd) AS total_fee_usd,
   stats_agg(fee) AS stats_fee_sat,
   avg(size) AS avg_tx_size,
   avg(weight) AS avg_tx_weight,
   count(
         CASE
            WHEN (fee > output_total) THEN hash
            ELSE NULL
         END) AS high_fee_count
  FROM transactions
  WHERE (is_coinbase IS NOT TRUE)
GROUP BY bucket;
"

psql -h localhost -U postgres -d bitcoin -c "
CREATE MATERIALIZED VIEW one_hour_blocks
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', time) AS bucket,
   block_id,
   count(*) AS tx_count,
   sum(fee) AS block_fee_sat,
   sum(fee_usd) AS block_fee_usd,
   stats_agg(fee) AS stats_tx_fee_sat,
   avg(size) AS avg_tx_size,
   avg(weight) AS avg_tx_weight,
   sum(size) AS block_size,
   sum(weight) AS block_weight,
   max(size) AS max_tx_size,
   max(weight) AS max_tx_weight,
   min(size) AS min_tx_size,
   min(weight) AS min_tx_weight
FROM transactions
WHERE is_coinbase IS NOT TRUE
GROUP BY bucket, block_id;
"

psql -h localhost -U postgres -d bitcoin -c "
CREATE MATERIALIZED VIEW one_hour_coinbase
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', time) AS bucket,
   count(*) AS tx_count,
   stats_agg(output_total, output_total_usd) AS stats_miner_revenue,
   min(output_total) AS min_miner_revenue,
   max(output_total) AS max_miner_revenue
FROM transactions
WHERE is_coinbase IS TRUE
GROUP BY bucket;
"

psql -h localhost -U postgres -d bitcoin -c "
SELECT add_continuous_aggregate_policy('one_hour_transactions',
   start_offset => INTERVAL '3 hours',
   end_offset => INTERVAL '1 hour',
   schedule_interval => INTERVAL '1 hour');

SELECT add_continuous_aggregate_policy('one_hour_blocks',
   start_offset => INTERVAL '3 hours',
   end_offset => INTERVAL '1 hour',
   schedule_interval => INTERVAL '1 hour');

SELECT add_continuous_aggregate_policy('one_hour_coinbase',
   start_offset => INTERVAL '3 hours',
   end_offset => INTERVAL '1 hour',
   schedule_interval => INTERVAL '1 hour');
"
```

Now generate descriptions for the schema objects:

```bash
uv run pgai semantic-catalog describe -d "postgres://postgres@localhost:5432/bitcoin" -f description.yaml
```

You can view the various descriptions that were generated in the `description.yaml`
file. Now we can create the semantic-catalog and import the descriptions:

```bash
uv run pgai semantic-catalog create -c "postgres://postgres@localhost:5432/bitcoin"
uv run pgai semantic-catalog import -d "postgres://postgres@localhost:5432/bitcoin" -f description.yaml
```

Modify your `.env` file for this repo to point at the bitcoin database:

```bash
DB_URL=postgresql://postgres:postgres@localhost:5432/bitcoin
```

Now generate 10 questions:

```bash
uv run python3 -m generator generate
```

Export to `evals` folder at top of repo:

```bash
uv run python3 -m generator export
```
