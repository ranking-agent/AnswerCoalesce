""" Answer Coalesce server. """
import os
import logging
import requests
import yaml
import json

from enum import Enum
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any

import httpx
from bmt import Toolkit
from pydantic import BaseModel, Field
from reasoner_pydantic import Response as PDResponse

from src.util import LoggingUtil
from src.default_query import default_input_sync
from src.single_node_coalescer import infer, multi_curie_query

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles


AC_VERSION = '3.1.1'

# get the location for the log
this_dir = os.path.dirname(os.path.realpath(__file__))

# init a logger
logger = LoggingUtil.init_logging('answer_coalesce', level=logging.INFO, format='long', logFilePath=this_dir + '/')

conf_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'config.json')
with open(conf_path, encoding="utf-8") as config_file:
    conf = json.load(config_file)

UI_DIR = Path(__file__).resolve().parent / "ui"
NAME_RESOLVER_URL = os.environ.get(
    "NAME_RESOLVER_URL",
    "https://name-resolution-sri.renci.org",
).rstrip("/")
NODE_NORMALIZER_URL = os.environ.get(
    "NODE_NORMALIZER_URL",
    conf["node_normalization_url"],
).rstrip("/")
if not NODE_NORMALIZER_URL.endswith("/get_normalized_nodes"):
    NODE_NORMALIZER_URL = f"{NODE_NORMALIZER_URL}/get_normalized_nodes"
IDENTITY_SERVICE_TIMEOUT = float(os.environ.get("IDENTITY_SERVICE_TIMEOUT", "20"))

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


class BatchLookupRequest(BaseModel):
    terms: list[str] = Field(min_length=1, max_length=100)
    limit: int = Field(default=5, ge=1, le=20)


class NormalizeRequest(BaseModel):
    curies: list[str] = Field(min_length=1, max_length=500)


default_request_sync: Body = Body(default=default_input_sync)


APP.mount("/ui/assets", StaticFiles(directory=UI_DIR), name="ui-assets")


@APP.get("/", include_in_schema=False)
@APP.get("/ui", include_in_schema=False)
async def user_interface():
    return FileResponse(UI_DIR / "index.html")


async def request_identity_service(method: str, url: str, **kwargs) -> Any:
    try:
        async with httpx.AsyncClient(timeout=IDENTITY_SERVICE_TIMEOUT) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
    except httpx.HTTPStatusError as err:
        logger.error("Identity service returned %s for %s", err.response.status_code, url)
        raise HTTPException(
            status_code=502,
            detail=f"Identity service returned HTTP {err.response.status_code}.",
        ) from err
    except httpx.RequestError as err:
        logger.error("Identity service request failed for %s: %s", url, err)
        raise HTTPException(
            status_code=502,
            detail="Identity service could not be reached.",
        ) from err

    return response.json()


def simplify_lookup_results(results: list[dict] | None) -> list[dict]:
    if not isinstance(results, list):
        return []
    return [
        {
            "curie": result.get("curie"),
            "label": result.get("label"),
            "types": result.get("types", []),
            "taxa": result.get("taxa", []),
            "score": result.get("score"),
        }
        for result in results
        if result.get("curie")
    ]


@lru_cache(maxsize=1)
def get_biolink_type_metadata() -> dict[str, dict[str, Any]]:
    toolkit = Toolkit()
    metadata = {}
    for category in toolkit.get_all_classes(formatted=True):
        element = toolkit.get_element(category)
        ancestors = toolkit.get_ancestors(category, formatted=True, reflexive=True) or []
        metadata[category] = {
            "depth": len(ancestors),
            "abstract": bool(getattr(element, "abstract", False)),
            "mixin": bool(getattr(element, "mixin", False)),
        }
    return metadata


@APP.get("/ui-api/biolink-types", tags=["UI support"])
async def biolink_types():
    return {"types": get_biolink_type_metadata()}


@APP.get("/ui-api/resolve", tags=["UI support"])
async def resolve_name(
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(default=8, ge=1, le=20),
):
    results = await request_identity_service(
        "GET",
        f"{NAME_RESOLVER_URL}/lookup",
        params={
            "string": q,
            "autocomplete": "true",
            "highlighting": "false",
            "limit": limit,
        },
    )
    return {"query": q, "results": simplify_lookup_results(results)}


@APP.post("/ui-api/resolve-batch", tags=["UI support"])
async def resolve_names(request: BatchLookupRequest):
    terms = list(dict.fromkeys(term.strip() for term in request.terms if term.strip()))
    if not terms:
        raise HTTPException(status_code=422, detail="At least one non-empty term is required.")

    results = await request_identity_service(
        "POST",
        f"{NAME_RESOLVER_URL}/bulk-lookup",
        json={
            "strings": terms,
            "autocomplete": False,
            "highlighting": False,
            "limit": request.limit,
        },
    )
    return {
        "results": {
            term: simplify_lookup_results(results.get(term, []))
            for term in terms
        }
    }


@APP.post("/ui-api/normalize", tags=["UI support"])
async def normalize_curies(request: NormalizeRequest):
    curies = list(dict.fromkeys(curie.strip() for curie in request.curies if curie.strip()))
    if not curies:
        raise HTTPException(status_code=422, detail="At least one non-empty CURIE is required.")

    normalized = await request_identity_service(
        "POST",
        NODE_NORMALIZER_URL,
        json={
            "curies": curies,
            "conflate": True,
            "drug_chemical_conflate": True,
            "description": False,
            "individual_types": False,
            "include_taxa": True,
        },
    )
    entities = []
    for input_curie in curies:
        node = normalized.get(input_curie)
        if not node:
            entities.append({
                "input_curie": input_curie,
                "curie": input_curie,
                "label": input_curie,
                "types": [],
                "taxa": [],
                "normalized": False,
            })
            continue

        preferred = node.get("id") or {}
        entities.append({
            "input_curie": input_curie,
            "curie": preferred.get("identifier", input_curie),
            "label": preferred.get("label") or preferred.get("identifier") or input_curie,
            "types": node.get("type", []),
            "taxa": node.get("taxa", []),
            "information_content": node.get("information_content"),
            "equivalent_identifier_count": len(node.get("equivalent_identifiers", [])),
            "normalized": True,
        })

    return {"entities": entities}


@APP.post('/query', tags=["Answer coalesce"], response_model=PDResponse, response_model_exclude_none=True,
          status_code=200)
async def query_handler(request: PDResponse = default_request_sync):
    # """ Answer coalesce operations. You may choose all, property, graph. """

    try:
        # convert the incoming message into a dict
        in_message = request.dict(exclude_none=True)

        parameters = await get_parameters(in_message)

        if await is_infer_query(in_message):
            result = await infer(in_message)
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
