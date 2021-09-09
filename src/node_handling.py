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
    if old_id.startswith('CHEMBL'):
        x = old_id.split(':')
        old_id = f'CHEMBL.COMPOUND:{x[1]}'
    result = requests.get(f'https://nodenormalization-sri.renci.org/get_normalized_nodes?curie={old_id}')
    try:
        rj = result.json()
        new_id = rj[old_id]['id']['identifier']
        return new_id
    except:
        print(old_id)
        return None

def denormalize(new_id):
    old_id = new_id
    return old_id
