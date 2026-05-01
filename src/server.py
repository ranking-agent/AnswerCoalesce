""" Answer Coalesce server. """
import os
import hashlib
import logging
import requests
import yaml
import json
import uuid
import redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
import redis.exceptions
import orjson
import httpx
from datetime import datetime

from enum import Enum
from functools import wraps
from pydantic import BaseModel, Field
from typing import Optional
from reasoner_pydantic import Response as PDResponse

from src.util import LoggingUtil
from src.default_query import default_input_sync, default_input_infer
from src.single_node_coalescer import infer, multi_curie_query

from fastapi import Body, FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi


AC_VERSION = '3.1.0'

# get the location for the log
this_dir = os.path.dirname(os.path.realpath(__file__))

# init a logger
logger = LoggingUtil.init_logging('answer_coalesce', level=logging.INFO, format='long', logFilePath=this_dir + '/')

# load up the config file
conf_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'config.json')
with open(conf_path, 'r') as _cf:
    conf = json.load(_cf)

# Redis connection for async — defaults from config.json (same as graph coalescer)
REDIS_HOST = os.getenv("REDIS_HOST", conf.get("redis_host", "localhost"))
REDIS_PORT = int(os.getenv("REDIS_PORT", conf.get("redis_port", 6379)))
JOB_PREFIX = "ac:job:"
JOB_EXPIRY = 7200  # 2 hours

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
    retry=Retry(ExponentialBackoff(cap=10, base=0.5), retries=5),
    retry_on_error=[redis.exceptions.BusyLoadingError, redis.exceptions.ConnectionError, redis.exceptions.TimeoutError],
)

INFER_CACHE_PREFIX = "ac:infer:"
INFER_CACHE_TTL = int(os.getenv("INFER_CACHE_TTL", "3600"))
INFER_CACHE_ENABLED = os.getenv("INFER_CACHE_ENABLED", "true").lower() == "true"


def infer_cache_key(in_message: dict) -> str:
    qg = in_message.get("message", {}).get("query_graph", {})
    params = in_message.get("parameters", {}) or {}
    blob = orjson.dumps({"qg": qg, "params": params}, option=orjson.OPT_SORT_KEYS)
    return INFER_CACHE_PREFIX + hashlib.sha256(blob).hexdigest()


async def cached_infer(in_message: dict) -> dict:
    """Wrap infer() with a Redis result cache keyed by query_graph + parameters."""
    if not INFER_CACHE_ENABLED:
        return await infer(in_message)

    key = None
    try:
        key = infer_cache_key(in_message)
        cached = redis_client.get(key)
        if cached is not None:
            logger.info(f"infer cache HIT {key}")
            return orjson.loads(cached)
    except Exception as e:
        logger.warning(f"infer cache read failed: {e}")

    result = await infer(in_message)

    if key is not None and result is not None:
        try:
            redis_client.setex(key, INFER_CACHE_TTL, orjson.dumps(result, default=str))
            logger.info(f"infer cache SET {key} (ttl={INFER_CACHE_TTL}s)")
        except Exception as e:
            logger.warning(f"infer cache write failed: {e}")

    return result


# declare the application and populate some details
APP = FastAPI(
    title='Answer coalesce - A FastAPI UI/web service',
    version=AC_VERSION
)

# declare the crossorigin params
APP.add_middleware(CORSMiddleware,
                   allow_origins=['*'],
                   allow_credentials=True,
                   allow_methods=["*"],
                   allow_headers=["*"],
                   )


# declare the types of answer coalesce methods
class MethodName(str, Enum):
    all = "all"
    property = "property"
    graph = "graph"
    set = "set"


default_request_sync: Body = Body(default=default_input_sync)
default_request_infer: Body = Body(default=default_input_infer)


@APP.post('/query', tags=["Answer coalesce"], response_model=PDResponse, response_model_exclude_none=True,
          status_code=200)
async def query_handler(request: PDResponse = default_request_sync):
    # """ Answer coalesce operations. You may choose all, property, graph. """

    try:
        # convert the incoming message into a dict
        in_message = request.dict(exclude_none=True)

        parameters = await get_parameters(in_message)

        if await is_infer_query(in_message):
            result = await cached_infer(in_message)
        elif await is_multi_curie_query(in_message):
            result = await multi_curie_query(in_message, parameters)
        else:
            # This isn't a valid query
            status_code = 422
            logger.error(f"Invalid query.  Must be either a multi-curie query or an infer query.")
            return JSONResponse(content=in_message, status_code=status_code)

        # Convert ALL timestamps to strings (both old and new logs)
        convert_log_timestamps(result)
        return result

    except Exception as e:
        # put the error in the response
        status_code = 500
        logger.exception(f"Exception encountered {str(e)}")
        convert_log_timestamps(in_message)
        return JSONResponse(content=in_message, status_code=status_code)


class AsyncQueryRequest(BaseModel):
    message: dict
    callback: Optional[str] = Field(None, description="URL to POST results to when complete")
    parameters: Optional[dict] = None


@APP.post('/asyncquery', tags=["Answer coalesce"], response_model=None, status_code=202)
async def asyncquery_handler(background_tasks: BackgroundTasks, request: AsyncQueryRequest = default_request_infer):
    """Translator-compliant async query with optional callback.

    Submit a TRAPI query for background processing. Returns a job_id immediately.
    Poll /query/status/{job_id} and /query/result/{job_id} to track progress.
    If `callback` is provided, the full TRAPI response is POSTed to that URL on completion.
    """
    job_id = str(uuid.uuid4())
    in_message = request.dict(exclude_none=True)
    in_message.pop("callback", None)

    save_job(job_id, {
        "status": "running",
        "progress": 0,
        "result": None,
        "error": None,
        "created_at": datetime.utcnow().isoformat()
    })

    background_tasks.add_task(process_query, job_id, in_message, callback=request.callback)

    return {"job_id": job_id, "status": "running"}


@APP.get('/query/jobs', tags=["Answer coalesce"], response_model=None)
async def list_jobs():
    """List all active jobs."""
    keys = redis_client.keys(f"{JOB_PREFIX}*")
    jobs_list = []
    for key in keys[:100]:  # Limit to 100
        job_id = key.replace(JOB_PREFIX, "")
        job = get_job(job_id)
        if job:
            jobs_list.append({
                "job_id": job_id,
                "status": job.get("status"),
                "created_at": job.get("created_at"),
                "error": job.get("error")
            })
    return {"jobs": jobs_list, "count": len(jobs_list)}


@APP.get('/query/status/{job_id}', response_model=None)
async def get_job_status(job_id: str):
    """Check job status."""
    job = get_job(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    return {
        "job_id": job_id,
        "status": job["status"],
        "error": job.get("error")
    }


@APP.get('/query/result/{job_id}', response_model=None)
async def get_job_result(job_id: str):
    """Get job result when complete. Returns the same TRAPI Response format as /query."""
    job = get_job(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    if job["status"] != "completed":
        return JSONResponse({"error": "Job not complete", "status": job["status"]}, status_code=400)

    return JSONResponse(content=job["result"])


def save_job(job_id: str, job_data: dict):
    redis_client.setex(
        f"{JOB_PREFIX}{job_id}",
        JOB_EXPIRY,
        json.dumps(job_data, default=str)
    )


def get_job(job_id: str) -> dict | None:
    data = redis_client.get(f"{JOB_PREFIX}{job_id}")
    return json.loads(data) if data else None


def update_job(job_id: str, **updates):
    job = get_job(job_id)
    if job:
        job.update(updates)
        save_job(job_id, job)


async def process_query(job_id: str, in_message: dict, callback: str = None):
    """Background task to process the query. Fires callback if provided."""
    try:
        parameters = await get_parameters(in_message)

        if await is_infer_query(in_message):
            result = await cached_infer(in_message)
        elif await is_multi_curie_query(in_message):
            result = await multi_curie_query(in_message, parameters)
        else:
            update_job(job_id, status="failed", error="Invalid query type")
            if callback:
                await fire_callback(callback, in_message, job_id, error="Invalid query type")
            return

        convert_log_timestamps(result)
        update_job(job_id, status="completed", result=result)

        if callback:
            await fire_callback(callback, result, job_id)

    except Exception as e:
        logger.exception(f"Job {job_id} failed: {e}")
        update_job(job_id, status="failed", error=str(e))
        if callback:
            await fire_callback(callback, in_message, job_id, error=str(e))


async def fire_callback(callback_url: str, result: dict, job_id: str, error: str = None):
    """POST the result to the callback URL. Best-effort — log and move on if it fails."""
    payload = result if not error else {"error": error, "job_id": job_id}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(callback_url, json=payload)
            logger.info(f"Callback to {callback_url} returned {resp.status_code} for job {job_id}")
    except Exception as e:
        logger.warning(f"Callback to {callback_url} failed for job {job_id}: {e}")


async def get_parameters(in_message):
    """Get the parameters from the incoming message.  If they are not present, return the defaults."""
    parameters = {"predicate_constraints": in_message.get('parameters', {}).get('predicate_constraints', []),
                  "property_constraints": in_message.get('parameters', {}).get('property_constraints', []),
                  "pvalue_threshold": in_message.get('parameters', {}).get('pvalue_threshold', None),
                  "max_results": in_message.get('parameters', {}).get('max_results', None)}
    return parameters


async def is_infer_query(in_message):
    """Check if the query is an infer query.  An infer query is a 1-hop with a single bound node.
    The one edge has "knowledge_type: inferred" """
    # Check the basic structure
    if not count_query_nodes(in_message) == 2:
        return False
    if not count_query_edges(in_message) == 1:
        return False

    # TODO: Ola to implement
    for edge_id, qedges in in_message.get("message", {}).get("query_graph", {}).get("edges", {}).items():
        if qedges.get("knowledge_type", "") == "inferred":
            return True

    return False


async def is_multi_curie_query(in_message):
    """Check if the query is a MCQ.  An MCQ has set_interpretation: MANY, and member_ids."""
    # Check the basic structure
    if not count_query_nodes(in_message) == 2:
        return False
    if not count_query_edges(in_message) == 1:
        return False
    # One of the query nodes must have set_interpretation: MANY and member_ids
    for node in in_message['message']['query_graph']['nodes']:
        if 'set_interpretation' in in_message['message']['query_graph']['nodes'][node]:
            if in_message['message']['query_graph']['nodes'][node]['set_interpretation'] == 'MANY':
                if 'member_ids' in in_message['message']['query_graph']['nodes'][node]:
                    return True
    return False


def count_query_nodes(in_message):
    """Count the number of nodes in the query."""
    return len(in_message['message']['query_graph']['nodes'])


def count_query_edges(in_message):
    """Count the number of edges in the query."""
    return len(in_message['message']['query_graph']['edges'])


def convert_log_timestamps(message):
    """Convert all log timestamps to strings for JSON serialization"""
    for log in message.get('logs', []):
        if 'timestamp' in log and not isinstance(log['timestamp'], str):
            log['timestamp'] = str(log['timestamp'])


def log_exception(method):
    """Wrap method."""

    @wraps(method)
    async def wrapper(*args, **kwargs):
        """Log exception encountered in method, then pass."""
        try:
            return await method(*args, **kwargs)
        except Exception as err:  # pylint: disable=broad-except
            logger.exception(err)
            raise

    return wrapper


def post(name, url, message, params=None):
    """
    launches a post request, returns the response.

    :param name: name of service
    :param url: the url of the service
    :param message: the message to post to the service
    :param params: the parameters passed to the service
    :return: dict, the result
    """
    if params is None:
        response = requests.post(url, json=message)
    else:
        response = requests.post(url, json=message, params=params)

    if not response.status_code == 200:
        msg = f'Error response from {name}, status code: {response.status_code}'

        logger.error(msg)
        return msg  # {'errmsg': create_log_entry(msg, 'Warning', code=response.status_code)}

    return response.json()


def normalize(message):
    """
    Calls node normalizer
    :param message:
    :return:
    """
    url = f'{conf["node_normalization_url"]}/response'

    normalized_message = post('Node Normalizer', url, message)

    return normalized_message


def construct_open_api_schema():
    if APP.openapi_schema:
        return APP.openapi_schema

    open_api_schema = get_openapi(
        title='Answer Coalesce',
        version=AC_VERSION,
        routes=APP.routes
    )

    open_api_extended_file_path = os.path.join(os.path.dirname(__file__), '../openapi-config.yaml')

    with open(open_api_extended_file_path) as open_api_file:
        open_api_extended_spec = yaml.load(open_api_file, Loader=yaml.SafeLoader)

    # gather up all the x-maturity and translator id data
    x_maturity = os.environ.get("MATURITY_KEY", "x-maturity")
    x_maturity_val = os.environ.get("MATURITY_VALUE", "production")
    x_translator_id = os.environ.get("INFORES_KEY", "translator_id")
    x_translator_id_val = os.environ.get("INFORES_VALUE", "infores:answer-coalesce")

    # Add the x-maturity data
    open_api_schema["info"][x_maturity] = x_maturity_val

    x_translator_extension = open_api_extended_spec.get("x-translator")
    x_trapi_extension = open_api_extended_spec.get("x-trapi")
    contact_config = open_api_extended_spec.get("contact")
    terms_of_service = open_api_extended_spec.get("termsOfService")
    servers_conf = open_api_extended_spec.get("servers")
    tags = open_api_extended_spec.get("tags")
    title_override = open_api_extended_spec.get("title") or 'Answer Coalesce'
    description = open_api_extended_spec.get("description")

    if tags:
        open_api_schema['tags'] = tags

    if x_translator_extension:
        # if x_translator_team is defined amends schema with x_translator extension
        open_api_schema["info"]["x-translator"] = x_translator_extension

    if x_trapi_extension:
        # if x_translator_team is defined amends schema with x_translator extension
        open_api_schema["info"]["x-trapi"] = x_trapi_extension

    if contact_config:
        open_api_schema["info"]["contact"] = contact_config

    if terms_of_service:
        open_api_schema["info"]["termsOfService"] = terms_of_service

    if description:
        open_api_schema["info"]["description"] = description

    if title_override:
        open_api_schema["info"]["title"] = title_override

    # adds support to override server root path
    server_root = os.environ.get('SERVER_ROOT', '/')

    # make sure not to add double slash at the end.
    server_root = server_root.rstrip('/') + '/'

    if servers_conf:
        for s in servers_conf:
            if s['description'].startswith('Default'):
                s['url'] = server_root if server_root != '/' else s['url']
                s['x-maturity'] = os.environ.get("MATURITY_VALUE", "maturity")
                s['x-location'] = os.environ.get("LOCATION_VALUE", "location")

        open_api_schema["servers"] = servers_conf

    return open_api_schema


APP.openapi_schema = construct_open_api_schema()