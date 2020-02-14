"""API documentation for Question Rewrite - Swagger UI and web service."""
from jinja2 import Environment, FileSystemLoader, Template
from requests import Response, Request
from sanic import Blueprint, response
from swagger_ui_bundle import swagger_ui_3_path

# build Swagger UI
env: Environment = Environment(loader=FileSystemLoader(swagger_ui_3_path))

# load a template
template: Template = env.get_template('index.j2')

# render the template using the parameters specified in the openapi spec
html_content: str = template.render(
    title="Question Rewrite - Swagger UI and web service",
    openapi_spec_url="./openapi.yml",
)

# render the opening page
with open('swagger_ui/index.html', 'w') as f:
    f.write(html_content)

# serve apidocs
bp: Blueprint = Blueprint('apidocs', url_prefix='/apidocs', strict_slashes=True)

# set static parameters
bp.static('/', 'swagger_ui/index.html')
bp.static('/', swagger_ui_3_path)
bp.static('/openapi.yml', 'swagger_ui/openapi.yml')


# define the redirected entry point
@bp.route('')
def redirect(request: Request) -> Response:
    """ Redirect to url with trailing slash. """
    return response.redirect('/apidocs/')
