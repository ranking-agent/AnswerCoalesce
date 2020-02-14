import os
import jsonschema
import yaml
import json
from sanic import Sanic, response
from sanic.request import Request

from QRW.apidocs import bp as apidocs_blueprint

""" Sanic server for Question Rewrite - A Swagger UI/web service. """

# initialize this web app
app: Sanic = Sanic("Question rewrite")

# suppress access logging
app.config.ACCESS_LOG = False

# init the app using the paramters defined in
app.blueprint(apidocs_blueprint)


@app.post('/query')
async def query_handler(request: Request) -> json:
    """ Handler for question rewrite operations. """

    # get the location of the Translator specification file
    dir_path: str = os.path.dirname(os.path.realpath(__file__))

    # load the Translator specification
    with open(os.path.join(dir_path, 'translator_interchange_0.9.0.yaml')) as f:
        spec: dict = yaml.load(f, Loader=yaml.SafeLoader)

    # load the query specification, first get the question node
    validate_with: dict = spec["components"]["schemas"]["Question"]

    # then get the components in their own array so the relative references are found
    validate_with["components"] = spec["components"]

    # remove the question node because we already have it at the top
    validate_with["components"].pop("Question", None)

    try:
        # load the input into a json object
        incoming: dict = json.loads(request.body)

        # validate the incoming json against the spec
        jsonschema.validate(instance=incoming, schema=validate_with)

    # all JSON validation errors are manifested as a thrown exception
    except jsonschema.exceptions.ValidationError as error:
        # print (f"ERROR: {str(error)}")
        return response.json({'Question failed validation. Message': str(error)}, status=400)

    # TODO: do the real work here. get a list of rewritten questions related to the requested one
    query_rewritten: list = [incoming, incoming]

    try:
        # validate each response item against the spec
        for item in query_rewritten:
            jsonschema.validate(item, validate_with)

    # all JSON validation errors are manifested as a thrown exception
    except jsonschema.exceptions.ValidationError as error:
        return response.json({'Response failed validation. Message': str(error)}, status=400)

    # if we are here the response validated properly
    return response.json(query_rewritten, status=200)
