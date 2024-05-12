""" Answer Coalesce server. """
import os
import logging
import requests
import yaml
import json

from enum import Enum
from functools import wraps
from reasoner_pydantic import Response as PDResponse

from src.util import LoggingUtil
from src.single_node_coalescer import infer, multi_curie_query

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

AC_VERSION = '3.0.0'

# get the location for the log
this_dir = os.path.dirname(os.path.realpath(__file__))

# init a logger
logger = LoggingUtil.init_logging('answer_coalesce', level=logging.INFO, format='long', logFilePath=this_dir+'/')

# declare the application and populate some details
APP = FastAPI(
    title='Answer coalesce - A FastAPI UI/web service',
    version=AC_VERSION
)

# declare the cross origin params
APP.add_middleware(
    CORSMiddleware,
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


# load up the config file
conf_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'config.json')
with open(conf_path, 'r') as inf:
    conf = json.load(inf)

@APP.post('/query', tags=["Answer coalesce"], response_model=PDResponse, response_model_exclude_none=True, status_code=200)
async def query_handler(request: PDResponse):
    # """ Answer coalesce operations. You may choose all, property, graph. """

    try:
        # convert the incoming message into a dict
        in_message = request.dict()

        # save the logs for the response (if any)
        if 'logs' not in in_message or in_message['logs'] is None:
            in_message['logs'] = []

        # these timestamps are causing json serialization issues in call to the normalizer
        # so here we convert them to strings.
        for log in in_message['logs']:
            log['timestamp'] = str(log['timestamp'])

        parameters = await get_parameters( in_message )

        if await is_infer_query( in_message ):
            return await infer( in_message, parameters )
        elif await is_multi_curie_query( in_message ):
            return await multi_curie_query( in_message, parameters )

        # This isn't a valid query
        status_code = 422
        logger.error(f"Invalid query.  Must be either a multi-curie query or an infer query.")
        return JSONResponse(content=in_message, status_code=status_code)

    except Exception as e:
        # put the error in the response
        status_code = 500
        logger.exception(f"Exception encountered {str(e)}")
        return JSONResponse(content=in_message, status_code=status_code)


async def get_parameters(in_message):
    """Get the parameters from the incoming message.  If they are not present, return the defaults."""
    parameters = {}
    parameters["predicates_to_exclude"] = in_message.get('parameters',{}).get('predicates_to_exclude', [])
    parameters["properties_to_exclude"] = in_message.get('parameters', {}).get('properties_to_exclude', [])
    parameters["pvalue_threshold"] = in_message.get('parameters', {}).get('pvalue_threshold', None)
    parameters["result_length"] = in_message.get('parameters', {}).get('result_length', None)
    return parameters

async def is_infer_query( in_message ):
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

    # Add the translator id (infores) data
    open_api_schema["info"][x_translator_id] = x_translator_id_val

    x_translator_extension = open_api_extended_spec.get("x-translator")
    x_trapi_extension = open_api_extended_spec.get("x-trapi")
    contact_config = open_api_extended_spec.get("contact")
    terms_of_service = open_api_extended_spec.get("termsOfService")
    servers_conf = open_api_extended_spec.get("servers")
    tags = open_api_extended_spec.get("tags")
    title_override = open_api_extended_spec.get("title") or 'ARAGORN Ranker'
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
                s['url'] = server_root + '1.4' if server_root != '/' else s['url']
                s['x-maturity'] = os.environ.get("MATURITY_VALUE", "maturity")
                s['x-location'] = os.environ.get("LOCATION_VALUE", "location")

        open_api_schema["servers"] = servers_conf

    return open_api_schema


APP.openapi_schema = construct_open_api_schema()
