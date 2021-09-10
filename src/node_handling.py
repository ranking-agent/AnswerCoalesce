##
#
# We're using inputs from new translator, e.g. using node norm etc, but the various
# enrichments are based on old robokop.   So we need to do a little bit of shimming to
# go back and forth on identifiers :(
#
# This is just temporary.  Once we can build the enhancement off the new automat services or
# some translator-wide big KG, we can drop this
#
##
import requests
import json
import os

def normalize(old_id):
    if old_id.startswith('CHEMBL:'):
        x = old_id.split(':')
        old_id = f'CHEMBL.COMPOUND:{x[0]}{x[1]}'
    elif old_id.startswith('gtpo'):
        x = old_id.split(':')
        old_id = f'GTOPDB:{x[1]}'

    conf_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'config.json')
    with open(conf_path, 'r') as inf:
        conf = json.load(inf)

    result = requests.get(f'{conf["node_normalization_url"]}/get_normalized_nodes?curie={old_id}')
    try:
        rj = result.json()
        new_id = rj[old_id]['id']['identifier']
        return new_id
    except:
        print(f'Failed normalization:{old_id}')
        return None

def denormalize(new_id):
    old_id = new_id
    return old_id
