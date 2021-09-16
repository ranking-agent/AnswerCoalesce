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
from src.single_node_coalescer import coalesce
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.encoders import jsonable_encoder

# get the location for the log
this_dir = os.path.dirname(os.path.realpath(__file__))

# init a logger
logger = LoggingUtil.init_logging('answer_coalesce', level=logging.INFO, format='long', logFilePath=this_dir+'/')

# declare the application and populate some details
APP = FastAPI(
    title='Answer coalesce - A FastAPI UI/web service',
    version='2.0.1'
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


def create_log_entry(msg: str, err_level, code=None) -> dict:
    """
    Creates a trapi log message

    :param msg:
    :param err_level:
    :param code:
    :return: dict of the data passed
    """
    # load the data
    ret_val = {
        'timestamp': str(datetime.now()),
        'level': err_level,
        'message': msg,
        'code': code
    }

    # return to the caller
    return ret_val

# load up the config file
conf_path = os.path.join(os.path.abspath(os.path.dirname(__file__)),'..','config.json')
with open(conf_path, 'r') as inf:
    conf = json.load(inf)

@APP.post('/coalesce/{method}', tags=["Answer coalesce"], response_model=PDResponse, response_model_exclude_none=True, status_code=200)
async def coalesce_handler(request: PDResponse, method: MethodName):
    """ Answer coalesce operations. You may choose all, property, graph. """

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
    #0 results is perfectly legal, there's just nothing to do.
    if 'results' not in in_message['message'] or len(in_message['message']['results']) == 0:
        status_code = 200
        in_message['logs'].append(create_log_entry(f'No results to coalesce', "WARNING"))
        return JSONResponse(content=in_message, status_code=status_code)

    elif 'knowledge_graph' not in in_message['message'] or len(in_message['message']['knowledge_graph']) == 0:
        #This is a 422 b/c we do have results, but there's no graph to use.
        status_code = 422
        in_message['logs'].append(create_log_entry(f'No knowledge graph to coalesce', "ERROR"))
        return JSONResponse(content=in_message, status_code=status_code)

    # init the status code
    status_code: int = 200

    # get the message to work on
    coalesced = in_message['message']

    try:
        # call the operation with the message in the request message
        coalesced = coalesce(coalesced, method=method)

        # turn it back into a full trapi message
        in_message['message'] = coalesced

        # import json
        # with open('ac_out_attributes.json', 'w') as tf:
        #     tf.write(json.dumps(in_message, default=str))

        # Normalize the data
        coalesced = normalize(in_message)

        # save the response in the incoming message
        in_message['message'] = coalesced['message']

        # validate the response again after normalization
        in_message = jsonable_encoder(PDResponse(**in_message))
    except Exception as e:
        # put the error in the response
        status_code = 500
        in_message['logs'].append(create_log_entry(f'Exception {str(e)}', "ERROR"))

    # return the result to the caller
    return JSONResponse(content=in_message, status_code=status_code)


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
        return {'errmsg': create_log_entry(msg, 'Warning', code=response.status_code)}

    return response.json()


def normalize(message):
    """
    Calls node normalizer
    :param message:
    :return:
    """
    url = f'{conf["node_normalization_url"]}/response' #  'https://nodenormalization-sri-dev.renci.org/1.1/response'  # 'http://localhost:5000/response'

    normalized_message = post('Node Normalizer', url, message)

    return normalized_message


def construct_open_api_schema():

    if APP.openapi_schema:
        return APP.openapi_schema

    open_api_schema = get_openapi(
        title='Answer Coalesce',
        version='2.0.1',
        routes=APP.routes
    )

    open_api_extended_file_path = os.path.join(os.path.dirname(__file__), '../openapi-config.yaml')

    with open(open_api_extended_file_path) as open_api_file:
        open_api_extended_spec = yaml.load(open_api_file, Loader=yaml.SafeLoader)

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

    if servers_conf:
        for s in servers_conf:
            s['url'] = s['url'] + '/1.2'
        open_api_schema["servers"] = servers_conf

    return open_api_schema


APP.openapi_schema = construct_open_api_schema()
