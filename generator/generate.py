from anthropic import Anthropic
from anthropic.types import (
    Message,
    MessageParam,
    TextBlock,
    ToolUseBlock,
    ThinkingBlock,
    ToolUseBlockParam,
    ToolResultBlockParam,
    ThinkingBlockParam,
)
from crayons import blue
import json
from textwrap import dedent
from typing import Any, Optional

from .data import load_questions, save_question
from .database import execute_query, generate_sql, get_schema_description
from .log import print_msg
from .utils import split_number


user_prompt = """
Generate %d questions that can be answered using a SQL statement querying this database model.
%d questions should be easy.
%d questions should be intermediate.
%d questions should be hard.

Interesting variations on these are allowed, but do not repeat them verbatim
""".strip()


def questions_system_prompt(
    prompt: str, schema_description: str, past_questions: list[tuple[str, str]], session_questions: list[tuple[str, str]]
) -> str:
    system_prompt = prompt.replace("{schema_description}", schema_description)

    for questions in [past_questions, session_questions]:
        session = "a previous session" if questions == past_questions else "the current session"
        if len(questions) > 0:
            formatted_questions = ""
            for i, t in enumerate(questions):
                formatted_questions += f"{i}. [{t[1]}] {t[0]}\n"

            system_prompt += dedent(f"""
            Below are questions that have invented in {session}:
            {formatted_questions}
            """).rstrip()
    return system_prompt


def send_message(
    client: Anthropic,
    system: str,
    messages: list[MessageParam],
    tools: Optional[list[dict[str, Any]]] = None,
) -> Message:
    if tools is None:
        tools = []
    return client.messages.create(
        max_tokens=20000,
        model="claude-3-7-sonnet-latest",
        stream=False,
        thinking={"type": "enabled", "budget_tokens": 16000},
        system=system,
        messages=messages,
        tools=tools,
    )


def send_generate_message(
    client: Anthropic, system: str, messages: list[MessageParam]
) -> Message:
    return send_message(
        client,
        system,
        messages,
        [
            {
                "name": "execute_query",
                "description": "Execute a query and returns the results in json format",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "select_statement": {
                            "type": "string",
                            "description": "The SQL SELECT statement to execute.",
                        }
                    },
                    "required": ["select_statement"],
                },
            },
            {
                "name": "record_question",
                "description": "Records a question about the dataset that may be answered using a SQL statement.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "A question about the dataset that might be posed by a user or data analyst.",
                        },
                        "complexity": {
                            "type": "string",
                            "enum": ["easy", "intermediate", "hard"],
                            "description": "An estimate of how complex the question is.",
                            "default": "easy",
                        },
                    },
                    "required": ["question", "complexity"],
                },
            },
        ],
    )


def fix_sql(
    client: Anthropic,
    prompt: str,
    schema_description: str,
    question: str,
    sql: str,
    results: None | list[dict[str, Any]],
    error: None | dict[str, Any],
) -> tuple[bool, str, str, bool, str]:
    message = dedent(f"""
        Given the following question, SQL query, and results, determine if the query adequately answers the question.
        If the question does not adequately answer the question, try to provide a fixed version of the SQL query.
        If the SQL query is not fixable, please provide a reason on why the question couldn't be answered by
        the SQL query.

        Here is a question that can be answered with the database:
        <question>
        {question}
        </question>
        Here is a SQL query to address the question:
        <sql>
        {sql}
        </sql>
    """).strip()

    if error is not None:
        message += dedent(f"""
            Here is an error that occurred when executing the SQL query:
            <error>
            {error}
            </error>
        """).rstrip()
    else:
        message += dedent(f"""
            Here are the first 10 results of the query in json format:
            <results_json>
            {json.dumps(results, indent=2)}
            </results_json>
        """).rstrip()

    response = send_message(
        client,
        dedent(f"""
            {prompt.split("\n")[0]}

            Below is the database schema description. Analyze and understand the schema.

            {schema_description}

            You MUST call the `record_answer` tool to record whether the SQL query adequately answers the question.
            """).rstrip(),
        [
            MessageParam(
                role="user",
                content=message,
            )
        ],
        [
            {
                "name": "record_answer",
                "description": "Records whether the query adequately addresses the question posed",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "modify_sql": {
                            "type": "boolean",
                            "description": "Whether the query was modified by the LLM.",
                        },
                        "fixed_sql": {
                            "type": "string",
                            "description": "The fixed SQL query, if applicable.",
                        },
                        "reason": {
                            "type": "string",
                            "description": "A reason for why the query needed to be changed if fixed_sql is provided.",
                        },
                        "fixable": {
                            "type": "boolean",
                            "description": "Whether the inadequacy is fixable.",
                        },
                        "fixable_reason": {
                            "type": "string",
                            "description": "An explanation of why the inadequacy is fixable or not.",
                        }
                    },
                    "required": ["modify_sql", "fixed_sql", "reason", "fixable", "fixable_reason"],
                },
            },
        ],
    )
    modify_sql = None
    for content_block in response.content:
        if (
            not isinstance(content_block, ToolUseBlock)
            or content_block.name != "record_answer"
        ):
            continue
        modify_sql = content_block.input["modify_sql"]
        sql = content_block.input.get("fixed_sql", "")
        reason = content_block.input.get("reason", "")
        fixable = content_block.input.get("fixable", "")
        fixable_reason = content_block.input.get("fixable_reason", "")

    if modify_sql is None:
        raise Exception("No adequacy found in response")
    return modify_sql, sql, reason, fixable, fixable_reason


def generate_questions(count: int, prompt: str) -> None:
    past_questions = load_questions()
    session_questions = []
    client = Anthropic()
    schema_description = get_schema_description()
    counts = split_number(count)
    generated_complexities = {
        "easy": counts[0],
        "intermediate": counts[1],
        "hard": counts[2],
    }
    print_msg(f"Generating {count} questions [{generated_complexities['easy']} easy, {generated_complexities['intermediate']} intermediate, {generated_complexities['hard']} hard]...")
    while True:
        if len(session_questions) >= count:
            break
        for c in generated_complexities:
            if generated_complexities[c] > 0:
                complexity = c
                break
        messages: list[MessageParam] = [
            MessageParam(
                role="user",
                content=f"Generate a {complexity} question that can be answered using a SQL statement querying this database model.",
            )
        ]
        print_msg("sending message...")
        response = send_generate_message(
            client, questions_system_prompt(prompt, schema_description, past_questions, session_questions), messages
        )
        for content_block in response.content:
            if isinstance(content_block, TextBlock):
                print_msg(f"text:\n{content_block.text}")
            elif isinstance(content_block, ThinkingBlock):
                print_msg(f"thinking:\n{content_block.thinking}")
                messages.append(
                    MessageParam(
                        role="assistant",
                        content=[
                            ThinkingBlockParam(
                                signature=content_block.signature,
                                thinking=content_block.thinking,
                                type="thinking",
                            )
                        ],
                    )
                )
            elif isinstance(content_block, ToolUseBlock):
                id = content_block.id
                inputs = content_block.input
                name = content_block.name
                messages.append(
                    MessageParam(
                        role="assistant",
                        content=[
                            ToolUseBlockParam(
                                id=id,
                                input=inputs,
                                name=name,
                                type="tool_use",
                            )
                        ],
                    )
                )
                if name == "execute_query":
                    query = inputs["select_statement"]
                    print_msg(f"executing query:\n{query}")
                    result, success = execute_query(query)
                    messages.append(
                        MessageParam(
                            role="user",
                            content=[
                                ToolResultBlockParam(
                                    tool_use_id=id,
                                    content=result,
                                    is_error=not success,
                                    type="tool_result",
                                )
                            ],
                        )
                    )
                elif name == "record_question":
                    question = inputs["question"]
                    complexity = inputs["complexity"]
                    print_msg(f"generated question:\n[{complexity}] {question}")
                    sql, sql_results, sql_error = generate_sql(question)
                    print_msg(f"generated sql:\n{sql}")
                    if sql_error is not None:
                        print_msg(f"error running sql:\n{sql_error}")
                    else:
                        print_msg(f"sql results:\n{sql_results}")

                    while True:
                        modified_sql, new_sql, reason, fixable, fixable_reason = fix_sql(
                            client,
                            prompt,
                            schema_description,
                            question,
                            sql,
                            sql_results,
                            sql_error,
                        )
                        if not modified_sql:
                            break
                        if not fixable:
                            print_msg(f"sql not fixable:\n{fixable_reason}")
                            messages.append(
                                MessageParam(
                                    role="user",
                                    content=[
                                        ToolResultBlockParam(
                                            tool_use_id=id,
                                            content=f"SQL query generated for the question is wrong, and cannot be fixed for the question. Reason: {fixable_reason}. Come up with a new question.",
                                            is_error=True,
                                            type="tool_result",
                                        )
                                    ],
                                )
                            )
                            break
                        print_msg(f"modified sql:\n{new_sql}\n{reason}")
                        sql = new_sql
                        result, success = execute_query(sql)
                        if not success:
                            print_msg(f"error running sql:\n{result}")
                            sql_error = result
                            sql_results = None
                        else:
                            print_msg(f"sql results:\n{sql_results}")
                            sql_results = result
                            sql_error = None
                    print_msg(f"question was adequate:\n{reason}")
                    print_msg("saving question")
                    # save_question(question, complexity)
                    session_questions.append((question, complexity))
                    generated_complexities[complexity] -= 1
                    messages.append(
                        MessageParam(
                            role="user",
                            content=[
                                ToolResultBlockParam(
                                    tool_use_id=id,
                                    content="question saved!",
                                    is_error=False,
                                    type="tool_result",
                                )
                            ],
                        )
                    )

                else:
                    raise Exception(f"Unrecognized tool: {name}")


def generate_prompt_base() -> str:
    client = Anthropic()
    schema_description = get_schema_description()
    print_msg("Generating prompt base...")
    resp = send_message(
        client,
        dedent(f"""
            You are an expert at generating prompts for LLMs. You understand and know SQL for
            PostgreSQL 17 and Timescale.

            Below is a description of schema of the database. Sample rows are included for
            each table. Analyze and understand the schema.

            {schema_description}
        """).strip(),
        messages=[
            MessageParam(
                role="user",
                content=dedent("""
                    Given the schema, generate a system prompt that can be used to guide a LLM to generate questions
                    that can be answered by SQL queries.

                    You should include the following information in the prompt:
                    > When generating questions, estimate how hard it would be to author the SQL to answer the
                    > question, ranking them as easy, intermediate, or hard.
                    > An easy question should only require one or two tables to answer.
                    > An intermediate question may require a few joins, aggregates, and/or window functions.
                    > A hard question may require many joins, self-joins, and/or recursive CTEs, etc.

                    Your generated system prompt should always mention that the LLM is an expert in SQL for
                    PostgreSQL 17 and Timescale.
                    The generated prompt should include the string {schema_description} to indicate where to
                    insert the schema description, with a space above and below it.
                    You should write something about the domain of the database, and the types of questions
                    that would be relevant or intresting to ask about the specific dataset.

                    You should not include any information about the database schema in your generated prompt.
                    You should not include any sample questions or questions in your generated prompt.
                    You should not include markdown header in the prompt.

                    Try to be concise and clear in the prompt you generate.
                """).strip(),
            )
        ],
        tools=[
            {
                "name": "record_prompt",
                "description": "Generated prompt for LLM",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "The prompt to use for the LLM.",
                        }
                    },
                    "required": ["prompt"],
                },
            }
        ]
    )
    for content_block in resp.content:
        if isinstance(content_block, ToolUseBlock) and content_block.name == "record_prompt":
            prompt = content_block.input["prompt"].strip()
            print(prompt)
            return prompt
    raise Exception("No prompt found in response")
