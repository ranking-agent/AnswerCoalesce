""" MultiCurie AC server. """
import os
import logging
import requests
import yaml
import json
from typing import List
from string import Template

from enum import Enum
from functools import wraps
from reasoner_pydantic import Response as PDResponse

from src.util import LoggingUtil
from src.multicurie_ac import multiCurieLookup

import fastapi
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

AC_VERSION = '2.1'

# get the location for the log
this_dir = os.path.dirname(os.path.realpath(__file__))

# init a logger
logger = LoggingUtil.init_logging('multiCurie-AC', level=logging.INFO, format='long', logFilePath=this_dir+'/')

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

# load up the config file
conf_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'config.json')
with open(conf_path, 'r') as inf:
    conf = json.load(inf)


@APP.post('/query/', tags=["MultiCurie AC Prototype"], response_model=PDResponse, response_model_exclude_none=True, status_code=200)
async def coalesce_handler(request: PDResponse):
    # """ Answer coalesce operations. You may choose all, property, graph. """

    # convert the incoming message into a dict
    in_message = request.dict()

    # save the logs for the response (if any)
    if 'logs' not in in_message or in_message['logs'] is None:
        in_message['logs'] = []

    # these timestamps are causing json serialization issues in call to the normalizer
    # so here we convert them to strings.
    for log in in_message['logs']:
        log['timestamp'] = str(log['timestamp'])

    # make sure there are results to coalesce
    # 0 results is perfectly legal, there's just nothing to do.
    if 'query_graph' not in in_message['message'] or len(in_message['message']['query_graph']) == 0:
        # This is a 422 b/c we do have results, but there's no graph to use.
        status_code = 422
        logger.error(f"No set to coalesce")
        # in_message['logs'].append(create_log_entry(f'No knowledge graph to coalesce', "ERROR"))
        return JSONResponse(content=in_message, status_code=status_code)

    # init the status code
    status_code: int = 200

    # get the message to work on
    coalesced = in_message['message']

    try:
        # call the operation with the message in the request message

        coalesced = multiCurieLookup(coalesced)

        # turn it back into a full trapi message
        in_message['message'] = coalesced

        assert PDResponse.parse_obj(in_message)

    except Exception as e:
        # put the error in the response
        status_code = 500
        logger.exception(f"Exception encountered {str(e)}")

    return JSONResponse(content=in_message, status_code=status_code)

@APP.get('/query/{qg}', summary="Get the enrichment for the multicurie(s) entered.", description="MultiCurie AC Prototype")
async def get_enrichment_handler(
    curie: List[str] = fastapi.Query([], description="List of curies to enrich",
        example=["NCBIGene:3952", "NCBIGene:9370"], min_items=1),
    predicates: List[str] = fastapi.Query([], description="List of curies to predicates",
        example=["biolink:affects"], min_items=1,),
    target_category: str = fastapi.Query(example="biolink:Gene", description="node type of the input list"),
    source_category: str = fastapi.Query(example="biolink:ChemicalEntity", description="Return type"),
    object_aspect_qualifier: str = fastapi.Query(example="activity_or_abundance", description="Qualifier"),
    object_direction_qualifier: str = fastapi.Query(example="increased", description="Qualifier direction"),
    is_source: bool = fastapi.Query(False, description="Whether the genelist is subject or target"),
):
    """
    Get trapi parameters
    """

    # in_message = get_qg(curie, predicates, source_category, target_category, is_source, object_aspect_qualifier, object_direction_qualifier)
    # coalesced = in_message["message"]
    #
    # # init the status code
    # status_code: int = 200
    # # turn it back into a full trapi message
    # try:
    #     # call the operation with the message in the request message
    #
    #     coalesced = multiCurieLookup(coalesced)
    #
    #     # turn it back into a full trapi message
    #     in_message['message'] = coalesced
    #
    #     assert PDResponse.parse_obj(in_message)
    #
    # except Exception as e:
    #     # put the error in the response
    #     logger.exception(f"Exception encountered {str(e)}")
    #     status_code = 500
    #     raise HTTPException(detail="Error occurred during processing.", status_code=status_code)

    # return JSONResponse(content=in_message, status_code=status_code)
    return {"message": multiCurieLookup(get_qg(curie, predicates, source_category, target_category, is_source, object_aspect_qualifier, object_direction_qualifier))}

def qg_template():
    return '''{
        "query_graph": {
            "nodes": {
                "$source": {
                    "ids": $source_id,
                    "constraints": [],
                    "is_set": false,
                    "categories":  $source_category
                },
                "$target": {
                    "ids": $target_id,
                    "is_set": false,
                    "constraints": [],
                    "categories": $target_category
                    }
            },
            "edges": {
                "e00": {
                    "subject": "$source",
                    "object": "$target",
                    "predicates":
                        $predicate
                    ,
                    "attribute_constraints": [],
                    "qualifier_constraints": $qualifier

                }
            }
        }
    }
'''

def get_qg(curie, predicates, source_category, target_category, is_source, object_aspect_qualifier=None, object_direction_qualifier=None):
    if is_source:
        target_ids = curie
        source_ids = []
    else:
        source_ids = curie
        target_ids = []

    source = source_category.split(":")[1].lower() if source_category else 'n0'
    target = target_category.split(":")[1].lower() if target_category else 'n1'
    query_template = Template(qg_template())
    query = {}

    # source_ids = source_ids if source_ids != None else []

    # is_source = True if source_ids else False

    quali = []
    if object_aspect_qualifier and object_direction_qualifier:
        quali = [
            {
                "qualifier_set": [
                    {
                        "qualifier_type_id": "biolink:object_aspect_qualifier",
                        "qualifier_value": object_aspect_qualifier
                    },
                    {
                        "qualifier_type_id": "biolink:object_direction_qualifier",
                        "qualifier_value": object_direction_qualifier
                    }
                ]
            }
        ]


    qs = query_template.substitute(source=source, target=target, source_id=json.dumps(source_ids),
                                   target_id=json.dumps(target_ids),
                                   source_category=json.dumps([source_category]),
                                   target_category=json.dumps([target_category]), predicate=json.dumps(predicates),
                                   qualifier=json.dumps(quali))

    try:
        query = json.loads(qs)
        if is_source:
            del query["query_graph"]["nodes"][source]["ids"]
            query["query_graph"]["nodes"][target]["is_set"] = True
        else:
            del query["query_graph"]["nodes"][target]["ids"]
            query["query_graph"]["nodes"][source]["is_set"] = True
    except UnicodeDecodeError as e:
        print(e)
    return query

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
