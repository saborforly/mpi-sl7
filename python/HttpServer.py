#coding=utf-8
from BaseHTTPServer import HTTPServer,BaseHTTPRequestHandler
import json
import Queue
import threading

message_queue=Queue.Queue()
class MyHandler(BaseHTTPRequestHandler):    
    def do_GET(self):
        self.wfile.write("这是一个http后台服务。".encode())
    def do_POST(self):
        data = self.rfile.read(int(self.headers["content-length"]))
        data = json.loads(data.decode())
        self.send_response(200)
        self.end_headers()
        message_queue.put(data)
        res = json.dumps({"tag":data['status'],"res":"success"})
        self.wfile.write(res.encode())
        print(data['status'])
        
    
class HttpThread(threading.Thread):
    def __init__(self,ip='', port=''):
        threading.Thread.__init__(self,name='HttpServer')
        self.myHandler = MyHandler
        self.ip = ip
        self.port = port
        #self.master = master
        #self.cond = cond
        self.sleep_flag = False
        self.jupyterTask_queue = message_queue
        
    def get_jupyterTask_queue(self):
        return self.jupyterTask_queue
    
    def run(self):
        try:
            server=HTTPServer((self.ip,self.port),self.myHandler) #启动服务
            print ('welcome to  the  server.......')
            #print(self.myHandler.getMessage())
            server.serve_forever()# 循环监听请求，当接收到请求后调用
        except KeyboardInterrupt:
            print ('shuting  done         server')
        server.socket.close()

if  __name__=='__main__':
    http = HttpThread('202.122.33.185', 8082)
    #http.setDaemon(True)
    http.start()
    print("ok")
    #message = http.myHandler.getMessage()
    print(http.jupyterTask_queue.get())
    
