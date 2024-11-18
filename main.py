import yaml

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from linkml.generators.pydanticgen import PydanticGenerator
from linkml.linter.linter import Linter
from linkml.linter.formatters import JsonFormatter
from fastapi.responses import FileResponse, Response
from linkml_runtime.linkml_model.meta import SchemaDefinition
from openai import OpenAI
import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_THREAD_ID = os.getenv("OPENAI_THREAD_ID")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")

app = FastAPI(docs_url="/api/docs/", redoc_url="/api/redoc/")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


@app.post(
    "/api/gen-pydantic/",
    openapi_extra={
        "requestBody": {
            "content": {"application/x-yaml"},
            "required": True,
        },
    },
)
async def gen_pydantic(request: Request):
    raw_body = await request.body()
    try:
        data = yaml.safe_load(raw_body)
    except yaml.YAMLError:
        raise HTTPException(status_code=422, detail="Invalid YAML")

    try:
        schema = SchemaDefinition(**data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    generator = PydanticGenerator(schema=schema)
    pydantic_model = generator.serialize()

    with open("pydantic_model.py", "w") as f:
        f.write(pydantic_model)

    return FileResponse(
        "pydantic_model.py",
        media_type="application/octet-stream",
        filename="pydantic_model.py",
    )


@app.post(
    "/api/validate-linkml/",
    openapi_extra={
        "requestBody": {
            "content": {"application/x-yaml"},
            "required": True,
        },
    },
)
async def validate_linkml(request: Request):
    raw_body = await request.body()
    try:
        data = yaml.safe_load(raw_body)
    except yaml.YAMLError:
        raise HTTPException(status_code=422, detail="Invalid YAML")

    with open("schema.yaml", "w") as f:
        f.write(yaml.dump(data))

    problems = Linter.validate_schema("schema.yaml")

    with open("report.json", "w") as f:
        formatter = JsonFormatter(f)
        formatter.start_report()
        for problem in problems:
            formatter.handle_problem(problem)
        formatter.end_report()

        return FileResponse(
            "report.json", media_type="application/json", filename="report.json"
        )


@app.post("/api/openai/generate/")
async def generate(request: Request):
    if not (OPENAI_API_KEY and OPENAI_THREAD_ID and OPENAI_ASSISTANT_ID):
        return Response(
            status_code=500,
            content="OpenAI API key, thread ID, or assistant ID not set",
        )

    raw_body = await request.body()
    client = OpenAI(api_key=OPENAI_API_KEY)
    client.beta.threads.messages.create(
        thread_id=OPENAI_THREAD_ID, role="user", content=raw_body.decode("utf-8")
    )
    run = client.beta.threads.runs.create_and_poll(
        thread_id=OPENAI_THREAD_ID, assistant_id=OPENAI_ASSISTANT_ID
    )
    if run.status == "completed":
        messages = client.beta.threads.messages.list(thread_id=run.thread_id)

    return Response(content=messages.data[0].content[0].text.value)


@app.post("/api/openai/ask/")
async def ask(request: Request):
    if not (OPENAI_API_KEY):
        return Response(status_code=500, content="OpenAI API key not set")

    raw_body = await request.body()
    client = OpenAI(api_key=OPENAI_API_KEY)
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": raw_body.decode("utf-8"),
            },
        ],
    )

    return Response(content=completion.choices[0].message.content)
