#coding=utf-8
import httplib
import sys
import json
import re
from Util import Config 

Config.Config()
port_file = Config.Config.getCFGattr('rundir')+'/port.txt'

with open(port_file, 'r') as f:
    port_content = f.read()
    print(port_content)
    ip = re.findall(".*description#(.*)\$port.*",port_content)[0]
    port = re.findall(".*port#(.*)\$if.*",port_content)[0]
print(ip)
conn = httplib.HTTPConnection(ip, int(port)+1)
data = {"status":"start", "cut":{'cutQ':1 , 'cutT':2},"evt_filelist": '/junofs/users/liuyan/OEC/mpi/python'}
#data = {"status":"continue"}
data = json.dumps(data)
headers = {"Content-Type": "application/json"}
conn.request("POST", '/start', data, headers)
res = conn.getresponse()


print(res.read().decode("utf-8"))
