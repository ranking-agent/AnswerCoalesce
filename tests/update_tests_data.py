from upgrade_trapi import upgrade_Message
from reasoner_pydantic import Response as PDResponse
import json,os

indir = 'InputJson_1.2'
outdir = 'InputJson_1.4'

for filename in os.listdir(indir):
    with open(f'{indir}/{filename}','r') as inf,  open(f'{outdir}/{filename}','w') as outf:
        print(filename)
        input_message = json.load(inf)
        output_message = {'message': upgrade_Message(input_message['message'])}
        json.dump(output_message,outf,indent=4)

