import os
import jsonschema
import yaml
import json
from sanic import Sanic, response
from sanic.request import Request

from src.apidocs import bp as apidocs_blueprint
from src.single_node_coalescer import coalesce

""" Sanic server for Answer Coalesce - A Swagger UI/web service. """

# initialize this web app
app: Sanic = Sanic("Answer Coalesce")

# suppress access logging
app.config.ACCESS_LOG = False

# init the app using the parameters defined in
app.blueprint(apidocs_blueprint)


@app.post('/coalesce')
async def coalesce_handler(request: Request) -> json:
    """ Handler for Answer coalesce operations. """
    method = request.args.get('method', 'all')

    # get the location of the Translator specification file
    dir_path: str = os.path.dirname(os.path.realpath(__file__))

    # load the Translator specification
    with open(os.path.join(dir_path, 'translator_interchange_0.9.0.yaml')) as f:
        spec: dict = yaml.load(f, Loader=yaml.SafeLoader)

    # load the query specification, first get the result node
    validate_with: dict = spec["components"]["schemas"]["Result"]

    # then get the components in their own array so the relative references are found
    validate_with["components"] = spec["components"]

    # remove the result node because we already have it at the top
    validate_with["components"].pop("Result", None)

    try:
        # load the input into a json object
        incoming: dict = json.loads(request.body)

        # validate the incoming json against the spec
        jsonschema.validate(instance=incoming, schema=validate_with)

    # all JSON validation errors are manifested as a thrown exception
    except jsonschema.exceptions.ValidationError as error:
        # print (f"ERROR: {str(error)}")
        return response.json({'Result failed validation. Message': str(error)}, status=400)

    coalesced = coalesce(incoming, method=method)

    # try:
    #     # validate each response item against the spec
    #     for item in coalesced:
    #         jsonschema.validate(item, validate_with)
    #
    # # all JSON validation errors are manifested as a thrown exception
    # except jsonschema.exceptions.ValidationError as error:
    #     return response.json({'Response failed validation. Message': str(error)}, status=400)

    # if we are here the response validated properly
    return response.json(coalesced, status=200)
