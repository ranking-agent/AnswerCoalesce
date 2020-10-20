""" Answer Coalesce server. """
import os
import logging
from enum import Enum
from functools import wraps
from src.util import LoggingUtil
from reasoner_pydantic import Request, Message
from src.single_node_coalescer import coalesce
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# get the location for the log
this_dir = os.path.dirname(os.path.realpath(__file__))

# init a logger
logger = LoggingUtil.init_logging('answer_coalesce', level=logging.INFO, format='long', logFilePath=this_dir+'/')

# declare the application and populate some details
APP = FastAPI(
    title='Answer coalesce - A FastAPI UI/web service',
    version='0.1.0',
    description='A FastAPI UI/web service interface for the Answer Coalesce service',
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
    none = "--"
    all = "all"
    property = "property"
    graph = "graph"
    ontology = "ontology"


@APP.post('/coalesce/{method}')
async def coalesce_handler(request: Request, method: MethodName) -> Message:
    """ Answer coalesce operations. You ay choose all, property, graph or ontology analysis. """

    # did we get a good method
    if method != MethodName.none:
        # convert the incoming message into a dict
        message = request.message.dict()

        # call the operation with the request
        coalesced = coalesce(message, method=method)

        # return the result to the caller
        return Message(**coalesced)
    else:
        return "Invalid method selected"

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
