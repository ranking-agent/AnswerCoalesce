from reasoner_converter import upgrading
import json,os

indir = 'InputJson_0.9.2'
outdir = 'InputJson_1.0'

for filename in os.listdir(indir):
    with open(f'{indir}/{filename}','r') as inf,  open(f'{outdir}/{filename}','w') as outf:
        print(filename)
        input_message = json.load(inf)
        output_message = {'message': upgrading.upgrade_Message(input_message['message'])}
        json.dump(output_message,outf,indent=4)
